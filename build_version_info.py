# Генерирует version_info.txt для PyInstaller из version.py.

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from version import VERSION

parts = VERSION.split(".")
while len(parts) < 4:
    parts.append("0")
v = tuple(int(x) for x in parts[:4])

content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v},
    prodvers={v},
    mask=0x3f,
    flags=0x0,
    OS=0x4,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName',      u'GreyDesh'),
          StringStruct(u'FileDescription',  u'TempusLauncher'),
          StringStruct(u'FileVersion',      u'{VERSION}'),
          StringStruct(u'InternalName',     u'app'),
          StringStruct(u'ProductName',      u'TempusLauncher'),
          StringStruct(u'ProductVersion',   u'{VERSION}'),
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""

out = __import__('pathlib').Path(__file__).parent / "version_info.txt"
out.write_text(content, encoding="utf-8")
print(f"version_info.txt -> {VERSION}")
