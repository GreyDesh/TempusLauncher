"""OpenGL рендер модели игрока из GLB файла с анимациями Blockbench."""
import ctypes
import math
import time
import threading
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import *

import logging as _log
_logger = _log.getLogger("player_gl")

try:
    import pygltflib
    _HAS_GLTF = True
except ImportError as _e:
    _logger.warning(f"pygltflib недоступен: {_e}")
    _HAS_GLTF = False

# model/ лежит либо рядом с кодом (бандл: app/current/model), либо на уровень выше
# (dev из исходников: project_root/model). Берём тот, что существует.
_UI_DIR = Path(__file__).resolve().parent
_MODEL_DIR = next(
    (c for c in (_UI_DIR.parent / "model", _UI_DIR.parent.parent / "model") if c.exists()),
    _UI_DIR.parent / "model",
)
_ANIM_FILE   = _MODEL_DIR / "animations.glb"
_MODEL_FILES = {"steve": _MODEL_DIR / "stuve.glb", "alex": _MODEL_DIR / "alex.glb"}

DEFAULT_ANIM = "animation.player.idle"
INTRO_ANIM   = "animation.player.give_honor"

# Кэш дорогого CPU-парса glb (pygltflib) — общий на процесс, по имени модели.
# GL-ресурсы (VAO/текстуры) всё равно строятся per-context; кэшируем только
# распарсенные данные, чтобы не фризить UI при создании каждой PlayerGLWidget.
_PARSED_MODEL: dict = {}   # model_name -> (nodes, root, raw_mesh_data, tex_bytes)
_PARSED_ANIM:  dict = {}   # model_name -> anims dict
BLEND_DUR    = 0.25   # секунды перехода между анимациями


# ── Математика ────────────────────────────────────────────────────────────────

def _trs(t=None, r=None, s=None) -> np.ndarray:
    """T * R * S матрица 4x4 (аллоцирует — только при инициализации)."""
    M = np.eye(4, dtype=np.float32)
    _trs_into(M, t, r, s)
    return M


def _trs_into(M: np.ndarray, t=None, r=None, s=None):
    """T * R * S матрица 4x4 — пишет в существующий M без аллокаций."""
    M[:] = 0
    M[0,0] = M[1,1] = M[2,2] = M[3,3] = 1.0
    if r is not None:
        x, y, z, w = float(r[0]), float(r[1]), float(r[2]), float(r[3])
        M[0,0]=1-2*(y*y+z*z); M[0,1]=2*(x*y-w*z);   M[0,2]=2*(x*z+w*y)
        M[1,0]=2*(x*y+w*z);   M[1,1]=1-2*(x*x+z*z); M[1,2]=2*(y*z-w*x)
        M[2,0]=2*(x*z-w*y);   M[2,1]=2*(y*z+w*x);   M[2,2]=1-2*(x*x+y*y)
    if s is not None:
        M[0,:3] *= s[0]; M[1,:3] *= s[1]; M[2,:3] *= s[2]
    if t is not None:
        M[0,3]=t[0]; M[1,3]=t[1]; M[2,3]=t[2]


def _pivot_trs_into(M: np.ndarray, pivot, r=None, s=None):
    """T(pivot) · R · S · T(-pivot) — поворот вокруг опорной точки кости.

    Вершины хранятся в пространстве арматуры (не в локальных координатах кости),
    поэтому стандартный T*R*S вращает вокруг origin вместо pivot → нога улетает.
    Формула: translation_col = pivot - R3·S3 * pivot.
    """
    M[:] = 0; M[3,3] = 1.0
    if r is not None:
        x, y, z, w = float(r[0]), float(r[1]), float(r[2]), float(r[3])
        M[0,0]=1-2*(y*y+z*z); M[0,1]=2*(x*y-w*z);   M[0,2]=2*(x*z+w*y)
        M[1,0]=2*(x*y+w*z);   M[1,1]=1-2*(x*x+z*z); M[1,2]=2*(y*z-w*x)
        M[2,0]=2*(x*z-w*y);   M[2,1]=2*(y*z+w*x);   M[2,2]=1-2*(x*x+y*y)
    else:
        M[0,0] = M[1,1] = M[2,2] = 1.0
    if s is not None:
        M[0,:3] *= s[0]; M[1,:3] *= s[1]; M[2,:3] *= s[2]
    if pivot is not None:
        p0, p1, p2 = float(pivot[0]), float(pivot[1]), float(pivot[2])
        M[0,3] = p0 - (M[0,0]*p0 + M[0,1]*p1 + M[0,2]*p2)
        M[1,3] = p1 - (M[1,0]*p0 + M[1,1]*p1 + M[1,2]*p2)
        M[2,3] = p2 - (M[2,0]*p0 + M[2,1]*p1 + M[2,2]*p2)


def _slerp(q1, q2, t: float) -> np.ndarray:
    q1 = np.array(q1, np.float64); q2 = np.array(q2, np.float64)
    dot = np.dot(q1, q2)
    if dot < 0: q2, dot = -q2, -dot
    if dot > 0.9995:
        return (q1 + t * (q2 - q1)).astype(np.float32)
    th = math.acos(min(dot, 1.0))
    return ((math.sin((1-t)*th)*q1 + math.sin(t*th)*q2) / math.sin(th)).astype(np.float32)


def _perspective(fov, aspect, near, far) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov) / 2)
    return np.array([[f/aspect,0,0,0],[0,f,0,0],
                     [0,0,(far+near)/(near-far),(2*far*near)/(near-far)],
                     [0,0,-1,0]], np.float32)


def _look_at(eye, center, up) -> np.ndarray:
    f = np.array(center)-np.array(eye); f /= np.linalg.norm(f)
    r = np.cross(f, np.array(up));      r /= np.linalg.norm(r)
    u = np.cross(r, f)
    M = np.eye(4, dtype=np.float32); M[0,:3]=r; M[1,:3]=u; M[2,:3]=-f
    T = np.eye(4, dtype=np.float32); T[:3,3] = -np.array(eye)
    return M @ T


def _rot_y(deg) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    M = np.eye(4, dtype=np.float32)
    M[0,0]=c; M[0,2]=s; M[2,0]=-s; M[2,2]=c
    return M


def _interp(times, values, t: float, path: str) -> np.ndarray:
    if len(times) == 1:
        return values[0]
    t = max(float(times[0]), min(float(times[-1]), t))
    i = int(np.searchsorted(times, t, side='right')) - 1
    i = max(0, min(i, len(times)-2))
    dt = float(times[i+1]) - float(times[i])
    a  = (t - float(times[i])) / dt if dt > 1e-9 else 0.0
    if path == 'rotation':
        return _slerp(values[i], values[i+1], a)
    return values[i] + a * (values[i+1] - values[i])


# ── Шейдеры ───────────────────────────────────────────────────────────────────

_VERT = """
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;
layout(location=2) in vec2 aUV;
uniform mat4 uBone;
uniform mat4 uVP;
out vec3 vNormal;
out vec2 vUV;
void main(){
    vec4 world = uBone * vec4(aPos, 1.0);
    gl_Position = uVP * world;
    vNormal = normalize(mat3(uBone) * aNormal);
    vUV = aUV;
}
"""

_FRAG = """
#version 330 core
in vec3 vNormal;
in vec2 vUV;
uniform sampler2D uTex;
uniform vec3 uLightDir;
out vec4 FragColor;
void main(){
    vec4 col = texture(uTex, vUV);
    if(col.a < 0.05) discard;
    float diff = max(dot(normalize(vNormal), normalize(-uLightDir)), 0.0);
    float light = 0.45 + diff * 0.65;
    FragColor = vec4(col.rgb * light, col.a);
}
"""


def _compile(src, kind):
    s = glCreateShader(kind)
    glShaderSource(s, src); glCompileShader(s)
    if not glGetShaderiv(s, GL_COMPILE_STATUS):
        raise RuntimeError(glGetShaderInfoLog(s).decode())
    return s


def _make_prog():
    vs = _compile(_VERT, GL_VERTEX_SHADER)
    fs = _compile(_FRAG, GL_FRAGMENT_SHADER)
    p  = glCreateProgram()
    glAttachShader(p, vs); glAttachShader(p, fs)
    glLinkProgram(p)
    glDeleteShader(vs); glDeleteShader(fs)
    if not glGetProgramiv(p, GL_LINK_STATUS):
        raise RuntimeError(glGetProgramInfoLog(p).decode())
    return p


# ── GLB читатель ──────────────────────────────────────────────────────────────

_COMP = {5120:np.int8,5121:np.uint8,5122:np.int16,5123:np.uint16,5125:np.uint32,5126:np.float32}
_DIMS = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}


def _accessor(gltf, idx: int) -> np.ndarray:
    acc  = gltf.accessors[idx]
    bv   = gltf.bufferViews[acc.bufferView]
    blob = gltf.binary_blob()
    start = bv.byteOffset + (acc.byteOffset or 0)
    dims  = _DIMS[acc.type]
    data  = np.frombuffer(blob, dtype=_COMP[acc.componentType],
                          count=acc.count*dims, offset=start)
    return data.reshape(acc.count, dims) if dims > 1 else data


def _parse_model(gltf):
    nodes = []
    for i, n in enumerate(gltf.nodes):
        nodes.append({'name': n.name or '', 'idx': i, 'parent': None,
                      'children': list(n.children or []), 'mesh': n.mesh,
                      't': np.array(n.translation or [0,0,0], np.float32),
                      'r': np.array(n.rotation    or [0,0,0,1], np.float32),
                      's': np.array(n.scale       or [1,1,1], np.float32)})
    for nd in nodes:
        for ci in nd['children']:
            nodes[ci]['parent'] = nd['idx']

    root_idx = next(i for i,n in enumerate(nodes) if n['parent'] is None and n['children'])

    raw = []
    for ni, nd in enumerate(nodes):
        if nd['mesh'] is None: continue
        prim = gltf.meshes[nd['mesh']].primitives[0]
        pos = _accessor(gltf, prim.attributes.POSITION)
        nrm = (_accessor(gltf, prim.attributes.NORMAL)
               if prim.attributes.NORMAL is not None else np.zeros_like(pos))
        uvs = _accessor(gltf, prim.attributes.TEXCOORD_0)
        idx = _accessor(gltf, prim.indices).astype(np.uint16)
        raw.append({'node_idx': ni, 'pos': pos, 'nrm': nrm, 'uvs': uvs, 'idx': idx})

    tex_bytes = None
    if gltf.images:
        bv = gltf.bufferViews[gltf.images[0].bufferView]
        blob = gltf.binary_blob()
        tex_bytes = bytes(blob[bv.byteOffset: bv.byteOffset + bv.byteLength])

    return nodes, root_idx, raw, tex_bytes


def _close_anim_loop(anim: dict):
    """Делает зацикленную анимацию бесшовной.

    Короткие каналы (right_leg до 0.46s при анимации 2.5s) просто
    растягиваются до конца удерживанием последнего значения — нога стоит
    неподвижно, шов не нужен.
    Каналы полной длины чинят стык: values[-1] = values[0], чтобы
    микроскопическое расхождение экспорта не давало рывок при loop.
    """
    dur = anim['duration']
    for ch in anim['channels']:
        times  = ch['times']
        values = ch['values']
        if float(times[-1]) < dur - 1e-4:
            # Короткий канал — hold последнего значения, шов не трогаем
            ch['times']  = np.append(times,  np.float32(dur))
            ch['values'] = np.vstack([values, values[-1:]])
        else:
            # Полный канал — закрываем стык first=last
            values = values.copy()
            values[-1] = values[0]
            ch['values'] = values


def _parse_anims(gltf, model_nodes: list[dict]) -> dict[str, dict]:
    by_name = {nd['name']: nd['idx'] for nd in model_nodes if nd['name']}
    anims = {}
    for anim in gltf.animations:
        channels = []
        for ch in anim.channels:
            if ch.target.node is None: continue
            model_idx = by_name.get(gltf.nodes[ch.target.node].name)
            if model_idx is None: continue
            samp   = anim.samplers[ch.sampler]
            times  = _accessor(gltf, samp.input).astype(np.float32)
            values = _accessor(gltf, samp.output).astype(np.float32)
            if ch.target.path == 'rotation'    and values.ndim == 1: values = values.reshape(-1,4)
            if ch.target.path == 'translation' and values.ndim == 1: values = values.reshape(-1,3)
            # Нормализуем знаки кватернионов — q и -q одна ротация,
            # но slerp между ними идёт "длинным путём" и нога улетает
            if ch.target.path == 'rotation' and len(values) > 1:
                for i in range(1, len(values)):
                    if np.dot(values[i], values[i-1]) < 0:
                        values[i] = -values[i]
            # Удаляем одиночные выбросы — артефакт экспорта Blockbench:
            # один кейфрейм резко выбивается из плавной кривой и тут же возвращается.
            # Порог относительный: спайк детектируется только если он намного больше
            # типичного локального шага канала (защита от законных резких движений).
            if ch.target.path in ('translation', 'rotation') and len(values) > 2:
                norms = np.array([np.linalg.norm(values[i+1] - values[i])
                                  for i in range(len(values)-1)], dtype=np.float64)
                median_step = float(np.median(norms)) if len(norms) else 0.0
                keep = np.ones(len(values), dtype=bool)
                for i in range(1, len(values) - 1):
                    d_prev = float(norms[i-1])
                    d_next = float(norms[i])
                    d_span = np.linalg.norm(values[i+1] - values[i-1])
                    # Спайк: оба шага к соседям намного больше медианного шага,
                    # и сами соседи при этом близко друг к другу
                    if (d_prev > 8 * max(median_step, 1e-6) and
                            d_next > 8 * max(median_step, 1e-6) and
                            (d_prev + d_next) > 4 * max(d_span, 1e-6)):
                        keep[i] = False
                if not keep.all():
                    times  = times[keep]
                    values = values[keep]
            channels.append({'model_idx': model_idx, 'path': ch.target.path,
                             'times': times, 'values': values})
        if channels:
            anims[anim.name] = {'channels': channels,
                                'duration': max(ch['times'][-1] for ch in channels)}
    return anims


# ── GPU меш ───────────────────────────────────────────────────────────────────

class _Mesh:
    __slots__ = ['vao','vbo','ibo','count','node_idx']
    def __init__(self, vao, vbo, ibo, count, node_idx):
        self.vao=vao; self.vbo=vbo; self.ibo=ibo
        self.count=count; self.node_idx=node_idx


# ── Виджет ────────────────────────────────────────────────────────────────────

class PlayerGLWidget(QOpenGLWidget):
    _skin_ready = pyqtSignal(str, str)  # path, variant ("classic"|"slim")

    def __init__(self, model: str = "steve", parent=None, web_profile=None, transparent: bool = False):
        super().__init__(parent)
        self._transparent = transparent
        if transparent:
            # Прозрачный фон живого виджета: alpha в формате + композит поверх
            # родителя (под ним — градиент-карточка).
            from PyQt6.QtGui import QSurfaceFormat
            fmt = self.format()
            fmt.setAlphaBufferSize(8)
            self.setFormat(fmt)
            self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._model_name = model
        self._skin_path: Path | None = None
        self._cape_path: Path | None = None
        self._cape_ready = False           # текстура плаща загружена и плащ показывается
        self._prog   = None
        self._meshes: list[_Mesh] = []
        self._tex    = None
        self._cape_tex = None
        self._nodes: list[dict] = []
        self._root   = 0
        self._anims: dict[str, dict] = {}
        self._embedded_tex: bytes | None = None
        # pre-allocated буферы для _compute_bones (без аллокаций в render loop)
        self._local_buf:  np.ndarray | None = None   # (N,4,4)
        self._world_buf:  np.ndarray | None = None   # (N,4,4)
        self._blend_buf:  np.ndarray | None = None   # (N,4,4) для snapshot
        self._nd_map:     dict[int,int] = {}         # node_idx → позиция в буфере

        # анимация
        self._anim_name = INTRO_ANIM
        self._anim_time = 0.0
        self._anim_loop = False
        self._anim_next: str | None = DEFAULT_ANIM
        self._pending_anim: str | None = None   # set_animation до GL-инициализации
        self._pending_loop = True
        self._pending_next: str | None = None

        # блендинг между анимациями
        self._blend_from: dict[int, dict] | None = None
        self._blend_t = 0.0

        self._rot_y  = 180.0
        self._drag_x = None

        self._last_tick = time.perf_counter()

        self.setFixedSize(180, 280)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._skin_ready.connect(self._on_skin_ready)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(16)  # ~60 FPS (было 0 = без ограничения → 100% ядра)
        self._timer.start()

    # ── Публичное API ─────────────────────────────────────────────────────────

    def set_model(self, model: str):
        self._model_name = model
        self._blend_from = None
        self._blend_t = 0.0
        if self.isValid():
            self.makeCurrent()
            self._load_model()
            self._upload_texture()
            if self._cape_path:
                self._cape_ready = self._upload_cape()
            self._load_anims()
            self.doneCurrent()
        self.update()

    def restart_intro(self):
        """Перезапускает give_honor → idle при открытии диалога."""
        if INTRO_ANIM in self._anims:
            self._anim_name = INTRO_ANIM
            self._anim_time = 0.0
            self._anim_loop = False
            self._anim_next = DEFAULT_ANIM
            self._blend_from = None
            self._blend_t = 0.0
        elif DEFAULT_ANIM in self._anims:
            self._anim_name = DEFAULT_ANIM
            self._anim_time = 0.0
            self._anim_loop = True

    def set_animation(self, name: str, loop: bool = True, nxt: str | None = None):
        """nxt — что играть после (для цепочек, напр. cape.idle → cape.loop)."""
        if name in self._anims:
            self._snapshot_to_blend_buf()
            self._blend_from = True
            self._blend_t = 0.0
            self._anim_name = name
            self._anim_time = 0.0
            self._anim_loop = loop
            self._anim_next = nxt
        else:
            # GL ещё не инициализирован (_anims пусто) — применим после _load_anims
            self._pending_anim = name
            self._pending_loop = loop
            self._pending_next = nxt

    def set_clear_transparent(self):
        """Прозрачный фон рендера (для снимков-миниатюр на градиенте)."""
        if self.isValid():
            self.makeCurrent()
            glClearColor(0.0, 0.0, 0.0, 0.0)
            self.doneCurrent()

    def set_static_pose(self, name: str, rot_y: float = 180.0):
        """Замораживает статичную позу (один кадр, t=0) без блендинга/тика — для
        снимков-миниатюр. Кадр берётся ровно как есть, без плавных переходов."""
        self._blend_from = None
        self._blend_t = 0.0
        self._anim_name = name
        self._anim_time = 0.0
        self._anim_loop = False
        self._anim_next = None
        self._rot_y = rot_y

    def set_username(self, username: str, skin_variant: str = "classic", force_refresh: bool = False):
        model = "alex" if skin_variant == "slim" else "steve"
        if model != self._model_name:
            self.set_model(model)

        def _fetch():
            import base64, json as _j, requests
            from config import CACHE_DIR
            path = CACHE_DIR / f"skin_{username}.png"
            if force_refresh and path.exists():
                path.unlink()
            detected = skin_variant  # fallback
            try:
                uuid = requests.get(
                    f"https://api.mojang.com/users/profiles/minecraft/{username}",
                    timeout=8).json()["id"]
                props = requests.get(
                    f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid}",
                    timeout=8).json().get("properties", [])
                tex = next((p for p in props if p["name"] == "textures"), None)
                if tex:
                    tex_data = _j.loads(base64.b64decode(tex["value"]))
                    skin_data = tex_data["textures"]["SKIN"]
                    path.write_bytes(requests.get(skin_data["url"], timeout=10).content)
                    # Определяем вариант из метаданных
                    meta_model = skin_data.get("metadata", {}).get("model", "")
                    detected = "slim" if meta_model == "slim" else "classic"
            except Exception:
                if not path.exists(): return
            try:
                self._skin_ready.emit(str(path), detected)
            except RuntimeError:
                pass

        threading.Thread(target=_fetch, daemon=True).start()

    def set_skin(self, skin_path):
        self._skin_path = Path(skin_path) if skin_path else None
        if self.isValid():
            self.makeCurrent()
            self._upload_texture()
            self.doneCurrent()
        self.update()

    # ── OpenGL ────────────────────────────────────────────────────────────────

    _SS = 2  # коэффициент суперсэмплинга (2 = рендер в 2x, блит в 1x)

    def initializeGL(self):
        try:
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glClearColor(0.0, 0.0, 0.0, 0.0) if self._transparent else glClearColor(0.05, 0.05, 0.09, 1.0)
            self._prog = _make_prog()
            self._tex  = glGenTextures(1)
            self._cape_tex = glGenTextures(1)
            self._ss_fbo   = glGenFramebuffers(1)
            self._ss_color = glGenRenderbuffers(1)
            self._ss_depth = glGenRenderbuffers(1)
            self._ss_w = self._ss_h = 0
            self._load_model()
            self._upload_texture()
            self._load_anims()
            _logger.info(f"GL ok: meshes={len(self._meshes)} anims={list(self._anims)}")
        except Exception as e:
            _logger.exception(f"initializeGL: {e}")

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)
        sw, sh = w * self._SS, h * self._SS
        if sw != self._ss_w or sh != self._ss_h:
            self._ss_w, self._ss_h = sw, sh
            glBindRenderbuffer(GL_RENDERBUFFER, self._ss_color)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, sw, sh)
            glBindRenderbuffer(GL_RENDERBUFFER, self._ss_depth)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, sw, sh)
            glBindFramebuffer(GL_FRAMEBUFFER, self._ss_fbo)
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                      GL_RENDERBUFFER, self._ss_color)
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                      GL_RENDERBUFFER, self._ss_depth)
            glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def _is_cape_mesh(self, node_idx: int) -> bool:
        """Меш плаща = узел, названный 'cape', или чей РОДИТЕЛЬ — группа 'cape'
        (в наших моделях меш плаща лежит под узлом-группой 'cape')."""
        if not (0 <= node_idx < len(self._nodes)):
            return False
        nd = self._nodes[node_idx]
        if nd.get('name') == 'cape':
            return True
        par = nd.get('parent')
        return par is not None and self._nodes[par].get('name') == 'cape'

    def _render_scene(self):
        """Рисует сцену в текущий фреймбуфер."""
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if not self._prog or not self._meshes:
            return
        proj = _perspective(35, self._ss_w / max(self._ss_h, 1), 0.01, 100)
        view = _look_at([0, 1.0, 4.5], [0, 1.0, 0], [0, 1, 0])
        mrot = _rot_y(self._rot_y)
        vp   = proj @ view
        bones = self._compute_bones()
        glUseProgram(self._prog)
        glUniformMatrix4fv(glGetUniformLocation(self._prog, "uVP"), 1, GL_FALSE, vp.T.flatten())
        glUniform3f(glGetUniformLocation(self._prog, "uLightDir"), 0.3, -1.5, -2.0)
        glActiveTexture(GL_TEXTURE0)
        glUniform1i(glGetUniformLocation(self._prog, "uTex"), 0)
        for mesh in self._meshes:
            if self._is_cape_mesh(mesh.node_idx):
                if not self._cape_ready:
                    continue                   # плаща нет / снят — прячем меш плаща
                glBindTexture(GL_TEXTURE_2D, self._cape_tex)
            else:
                glBindTexture(GL_TEXTURE_2D, self._tex)
            bw = mrot @ bones.get(mesh.node_idx, np.eye(4, dtype=np.float32))
            glUniformMatrix4fv(glGetUniformLocation(self._prog, "uBone"), 1, GL_FALSE, bw.T.flatten())
            glBindVertexArray(mesh.vao)
            glDrawElements(GL_TRIANGLES, mesh.count, GL_UNSIGNED_SHORT, None)
        glBindVertexArray(0)

    def paintGL(self):
        if not self._ss_w or not self._prog:
            return
        # Тендер-гонка при уничтожении виджета: контекст/шейдер могут стать
        # невалидными между тиком и paintGL → glUseProgram даёт GL_INVALID_OPERATION.
        # Ловим, чтобы не ронять всё приложение фатальным исключением.
        try:
            glBindFramebuffer(GL_FRAMEBUFFER, self._ss_fbo)
            glViewport(0, 0, self._ss_w, self._ss_h)
            self._render_scene()
            dst = self.defaultFramebufferObject()
            glBindFramebuffer(GL_READ_FRAMEBUFFER, self._ss_fbo)
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, dst)
            w, h = self._ss_w // self._SS, self._ss_h // self._SS
            glBlitFramebuffer(0, 0, self._ss_w, self._ss_h, 0, 0, w, h,
                              GL_COLOR_BUFFER_BIT, GL_LINEAR)
            glBindFramebuffer(GL_FRAMEBUFFER, dst)
        except Exception as e:
            _logger.debug("paintGL skipped: %s", e)

    # ── Загрузка ──────────────────────────────────────────────────────────────

    def _load_model(self):
        if not _HAS_GLTF: return
        path = _MODEL_FILES.get(self._model_name, _MODEL_FILES["steve"])
        if not path.exists(): return

        for m in self._meshes:
            glDeleteVertexArrays(1,[m.vao]); glDeleteBuffers(1,[m.vbo]); glDeleteBuffers(1,[m.ibo])
        self._meshes.clear()

        # CPU-парс glb дорогой (pygltflib) — кэшируем на модель, чтобы не фризить
        # UI при каждом создании виджета (пикеры плодят по 2 модели за открытие).
        cached = _PARSED_MODEL.get(self._model_name)
        if cached is None:
            gltf = pygltflib.GLTF2().load(str(path))
            cached = _parse_model(gltf)     # (nodes, root, raw, tex_bytes)
            _PARSED_MODEL[self._model_name] = cached
        self._nodes, self._root, raw, self._embedded_tex = cached

        # Pre-allocate буферы — больше не создаём объекты в render loop
        n = len(self._nodes)
        self._local_buf = np.empty((n,4,4), dtype=np.float32)
        self._world_buf = np.empty((n,4,4), dtype=np.float32)
        self._blend_buf = np.empty((n,4,4), dtype=np.float32)
        self._nd_map    = {nd['idx']: i for i, nd in enumerate(self._nodes)}
        # Заполняем bind-pose
        for nd in self._nodes:
            self._local_buf[self._nd_map[nd['idx']]] = _trs(nd['t'], nd['r'], nd['s'])

        for rm in raw:
            vdata = np.hstack([rm['pos'].astype(np.float32),
                               rm['nrm'].astype(np.float32),
                               rm['uvs'].astype(np.float32)])
            idx   = rm['idx'].astype(np.uint16)
            vao=glGenVertexArrays(1); vbo=glGenBuffers(1); ibo=glGenBuffers(1)
            glBindVertexArray(vao)
            glBindBuffer(GL_ARRAY_BUFFER, vbo)
            glBufferData(GL_ARRAY_BUFFER, vdata.nbytes, vdata, GL_STATIC_DRAW)
            stride = 8*4
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,stride,ctypes.c_void_p(0))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,stride,ctypes.c_void_p(12))
            glEnableVertexAttribArray(2)
            glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,stride,ctypes.c_void_p(24))
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ibo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)
            glBindVertexArray(0)
            self._meshes.append(_Mesh(vao,vbo,ibo,len(idx),rm['node_idx']))

    def _load_anims(self):
        if not _HAS_GLTF or not _ANIM_FILE.exists() or not self._nodes: return
        # Парс animations.glb (много анимаций) дорогой — кэшируем на модель.
        cached = _PARSED_ANIM.get(self._model_name)
        if cached is None:
            gltf = pygltflib.GLTF2().load(str(_ANIM_FILE))
            cached = _parse_anims(gltf, self._nodes)
            _LOOP_ANIMS = {DEFAULT_ANIM, 'animation.player.disco_wip',
                           'animation.player.easy', 'animation.player.idle_gun_1',
                           'animation.player.idle_gun_2', 'walk', 'animation.dance.arm',
                           'animation.cape.loop'}
            for name in _LOOP_ANIMS:
                if name in cached:
                    _close_anim_loop(cached[name])
            _PARSED_ANIM[self._model_name] = cached
        self._anims = cached
        # Отложенная анимация (set_animation до GL-инициализации) — приоритетнее интро
        pending = getattr(self, "_pending_anim", None)
        if pending and pending in self._anims:
            self._anim_name = pending
            self._anim_time = 0.0
            self._anim_loop = getattr(self, "_pending_loop", True)
            self._anim_next = getattr(self, "_pending_next", None)
            self._blend_from = None
            self._pending_anim = None
        elif INTRO_ANIM in self._anims:
            self._anim_name = INTRO_ANIM
            self._anim_time = 0.0
            self._anim_loop = False
            self._anim_next = DEFAULT_ANIM
        else:
            self._anim_name = DEFAULT_ANIM
            self._anim_time = 0.0
            self._anim_loop = True
            self._anim_next = None

    def _upload_texture(self):
        img = None
        if self._skin_path and self._skin_path.exists():
            img = QImage(str(self._skin_path))
        elif self._embedded_tex:
            img = QImage(); img.loadFromData(self._embedded_tex)
        if img is None or img.isNull(): return

        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(img.bits().asarray(img.width()*img.height()*4))
        glBindTexture(GL_TEXTURE_2D, self._tex)
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,img.width(),img.height(),0,GL_RGBA,GL_UNSIGNED_BYTE,raw)
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE)

    def _upload_cape(self):
        """Грузит текстуру плаща (64×32) в _cape_tex. Возвращает True при успехе."""
        if not (self._cape_path and self._cape_path.exists()):
            return False
        img = QImage(str(self._cape_path))
        if img.isNull():
            return False
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(img.bits().asarray(img.width() * img.height() * 4))
        glBindTexture(GL_TEXTURE_2D, self._cape_tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, img.width(), img.height(), 0, GL_RGBA, GL_UNSIGNED_BYTE, raw)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        return True

    def set_cape(self, cape_path):
        """Ставит плащ (путь к 64×32) или снимает (None → меш плаща прячется)."""
        self._cape_path = Path(cape_path) if cape_path else None
        self._cape_ready = False
        if self._cape_path and self.isValid():
            self.makeCurrent()
            self._cape_ready = self._upload_cape()
            self.doneCurrent()
        self.update()

    def _on_skin_ready(self, path: str, variant: str):
        detected_model = "alex" if variant == "slim" else "steve"
        if detected_model != self._model_name:
            self.set_model(detected_model)
        self._skin_path = Path(path)
        if self.isValid():
            self.makeCurrent(); self._upload_texture(); self.doneCurrent()
        self.update()

    # ── Анимация ──────────────────────────────────────────────────────────────

    def _snapshot_to_blend_buf(self):
        """Копирует текущий local_buf в blend_buf для последующего блендинга."""
        if self._local_buf is not None and self._blend_buf is not None:
            np.copyto(self._blend_buf, self._local_buf)

    def _compute_bones(self) -> dict[int, np.ndarray]:
        if not self._nodes or self._local_buf is None: return {}

        local = self._local_buf
        world = self._world_buf
        nd_map_i = self._nd_map

        # Заполняем local матрицы
        anim = self._anims.get(self._anim_name)
        # Bind-pose
        for nd in self._nodes:
            bi = nd_map_i[nd['idx']]
            _trs_into(local[bi], nd['t'], nd['r'], nd['s'])

        # Накладываем анимацию — per-node собираем T/R/S затем строим матрицу
        if anim:
            dur = anim['duration']
            at  = self._anim_time % dur if dur > 0 else 0
            # Собираем переопределения по нодам
            # Каждый канал зацикливается по СВОЕЙ длительности — Blockbench
            # может экспортировать ноги с коротким циклом внутри длинной анимации
            ovr_t = {}; ovr_r = {}; ovr_s = {}
            for ch in anim['channels']:
                mi = ch['model_idx']
                val = _interp(ch['times'], ch['values'], at, ch['path'])
                if   ch['path'] == 'translation': ovr_t[mi] = val
                elif ch['path'] == 'rotation':    ovr_r[mi] = val
                elif ch['path'] == 'scale':       ovr_s[mi] = val
            for nd in self._nodes:
                mi = nd['idx']; bi = nd_map_i[mi]
                if mi in ovr_t or mi in ovr_r or mi in ovr_s:
                    _trs_into(local[bi],
                              ovr_t.get(mi, nd['t']),
                              ovr_r.get(mi, nd['r']),
                              ovr_s.get(mi, nd['s']))

        # Блендинг: lerp всей матрицы (src=blend_buf, dst=local, alpha=blend_t)
        if self._blend_from is not None and self._blend_t < 1.0:
            a = self._blend_t
            bf = self._blend_buf
            for nd in self._nodes:
                bi = nd_map_i[nd['idx']]
                local[bi] = bf[bi] + a * (local[bi] - bf[bi])

        # Обход дерева — мировые матрицы в world_buf (без аллокаций)
        _EYE = np.eye(4, dtype=np.float32)
        def _walk(idx: int, pw: np.ndarray):
            bi = nd_map_i[idx]
            np.matmul(pw, local[bi], out=world[bi])
            for ci in self._nodes[idx]['children']:
                _walk(ci, world[bi])
        _walk(self._root, _EYE)
        # возвращаем как node_idx → матрица (view в world_buf, не копия)
        return {nd['idx']: world[nd_map_i[nd['idx']]] for nd in self._nodes}

    # ── Тик ───────────────────────────────────────────────────────────────────

    def _tick(self):
        # контекст ещё не создан / уже уничтожен (виджет закрывают) — не трогаем GL
        if not self.isValid():
            return
        # окно скрыто в трее или свёрнуто — не рендерим и не считаем анимацию
        w = self.window()
        if not self.isVisible() or (w is not None and w.isMinimized()):
            self._last_tick = time.perf_counter()
            return
        now = time.perf_counter()
        dt  = min(now - self._last_tick, 0.05)
        self._last_tick = now
        anim = self._anims.get(self._anim_name)
        if anim:
            dur = anim['duration']
            self._anim_time += dt
            if self._anim_loop and self._anim_time >= dur:
                self._anim_time %= dur
            elif self._anim_loop:
                pass  # продолжаем
            elif self._anim_time >= dur:
                nxt = self._anim_next
                if nxt and nxt in self._anims:
                    self._snapshot_to_blend_buf()
                    self._blend_from = True
                    self._blend_t = 0.0
                    self._anim_name = nxt
                    self._anim_time = 0.0
                    self._anim_loop = True
                    self._anim_next = None
                else:
                    self._anim_time = dur
        if self._blend_from is not None:
            self._blend_t += dt / BLEND_DUR
            if self._blend_t >= 1.0:
                self._blend_from = None; self._blend_t = 0.0
        self.update()

    # ── Мышь ──────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_x = e.position().x()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag_x is not None:
            self._rot_y = (self._rot_y + (e.position().x()-self._drag_x)*0.5) % 360
            self._drag_x = e.position().x()
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag_x = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
