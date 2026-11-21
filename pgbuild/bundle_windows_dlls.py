"""Copy into an install tree's bin/ the DLLs its binaries import that Windows itself does not provide.

PostgreSQL built with MinGW-w64 can import runtime DLLs of the toolchain: PostgreSQL 18's postgres.exe imports
clock_gettime from libwinpthread-1.dll. The build machine has that DLL on PATH, so the binaries run there, but on a
machine without the toolchain they exit with STATUS_DLL_NOT_FOUND (0xC0000135). Windows looks for a DLL in the
executable's own folder first, so a copy next to the binaries is enough.

Usage: python bundle_windows_dlls.py <install prefix>
"""

import os
import shutil
import struct
import sys
from pathlib import Path


def imported_dlls(path: Path) -> list[str]:
    """The names of the DLLs a PE file (exe or dll) imports, read from its import directory."""
    data = path.read_bytes()
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe : pe + 4] != b'PE\0\0':
        raise ValueError(f'{path} is not a PE file')
    num_sections, optional_size = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
    optional = pe + 24
    is_pe32_plus = struct.unpack_from('<H', data, optional)[0] == 0x20B
    import_rva = struct.unpack_from('<I', data, optional + (112 if is_pe32_plus else 96) + 8)[0]
    if import_rva == 0:
        return []
    sections = [struct.unpack_from('<8sIIII', data, optional + optional_size + 40 * i) for i in range(num_sections)]

    def offset(rva: int) -> int:
        for _, virtual_size, virtual_address, raw_size, raw_offset in sections:
            if virtual_address <= rva < virtual_address + max(virtual_size, raw_size):
                return rva - virtual_address + raw_offset
        raise ValueError(f'{path}: RVA {rva:#x} is in no section')

    names = []
    entry = offset(import_rva)
    while True:
        name_rva = struct.unpack_from('<I', data, entry + 12)[0]
        if name_rva == 0:
            return names
        start = offset(name_rva)
        names.append(data[start : data.index(b'\0', start)].decode('ascii'))
        entry += 20


def provided_by_windows(name: str) -> bool:
    system32 = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
    return name.lower().startswith(('api-ms-win-', 'ext-ms-win-')) or (system32 / name).is_file()


def find_on_path(name: str) -> Path | None:
    for folder in os.environ.get('PATH', '').split(os.pathsep):
        if folder and (Path(folder) / name).is_file():
            return Path(folder) / name
    return None


def bundle(prefix: Path) -> list[str]:
    """Copy the missing DLLs (and the ones they import in turn) into prefix/bin; returns their names."""
    bin_dir = prefix / 'bin'
    local = {p.name.lower() for p in bin_dir.iterdir()}
    todo = [p for p in sorted(bin_dir.iterdir()) if p.suffix.lower() in ('.exe', '.dll')]
    todo += sorted((prefix / 'lib').glob('*.dll'))
    copied = []
    while todo:
        for name in imported_dlls(todo.pop()):
            if name.lower() in local or provided_by_windows(name):
                continue
            source = find_on_path(name)
            if source is None:
                raise SystemExit(f'{name} is imported by the binaries in {bin_dir} but is not on PATH')
            target = bin_dir / name
            shutil.copy2(source, target)
            local.add(name.lower())
            copied.append(name)
            todo.append(target)
    return copied


if __name__ == '__main__':
    for name in bundle(Path(sys.argv[1])):
        print(f'bundled {name}')
