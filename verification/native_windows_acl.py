"""Read Windows owner/DACL through Win32; never grant or change permissions."""
import os
import re


class ACLDenied(ValueError):
    pass


def need(ok):
    if not ok: raise ACLDenied('WINDOWS_PRIVATE_ACL_UNVERIFIED')


def sid_ok(value):
    return type(value) is str and len(value) <= 184 and re.fullmatch(r'S-\d-(?:\d+-)*\d+', value) is not None


def validate_acl(owner, current, entries):
    need(sid_ok(owner) and sid_ok(current) and owner == current
         and type(entries) is list and 0 < len(entries) <= 128)
    permitted = {current, 'S-1-5-18', 'S-1-5-32-544'}
    owner_allowed = False
    for row in entries:
        need(type(row) is tuple and len(row) == 4)
        kind, mask, identity, flags = row
        need(type(kind) is int and kind in (0, 1) and type(mask) is int
             and 0 <= mask <= 0xffffffff and sid_ok(identity)
             and type(flags) is int and 0 <= flags <= 255)
        if kind == 0:
            need(identity in permitted)
            owner_allowed |= identity == current and mask != 0 and not flags & 8
    need(owner_allowed)


def verify_private_acl(path):
    """Require current-user ownership and only user/SYSTEM/admin allow ACEs."""
    need(os.name == 'nt')
    import ctypes as c
    from ctypes import wintypes as w
    adv = c.WinDLL('advapi32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    ptr = c.c_void_p
    adv.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, w.DWORD, w.DWORD,
        c.POINTER(ptr), c.POINTER(ptr), c.POINTER(ptr), c.POINTER(ptr), c.POINTER(ptr)]
    adv.GetNamedSecurityInfoW.restype = w.DWORD
    adv.ConvertSidToStringSidW.argtypes = [ptr, c.POINTER(w.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = w.BOOL
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    adv.OpenProcessToken.restype = w.BOOL
    adv.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, ptr, w.DWORD, c.POINTER(w.DWORD)]
    adv.GetTokenInformation.restype = w.BOOL
    adv.GetAclInformation.argtypes = [ptr, ptr, w.DWORD, c.c_int]
    adv.GetAclInformation.restype = w.BOOL
    adv.GetAce.argtypes = [ptr, w.DWORD, c.POINTER(ptr)]
    adv.GetAce.restype = w.BOOL
    kernel.GetCurrentProcess.argtypes = []; kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]; kernel.CloseHandle.restype = w.BOOL
    kernel.LocalFree.argtypes = [ptr]; kernel.LocalFree.restype = ptr

    def sid_text(address):
        value = w.LPWSTR()
        need(bool(address) and bool(adv.ConvertSidToStringSidW(address, c.byref(value))))
        try: return value.value
        finally: kernel.LocalFree(c.cast(value, ptr))

    token = w.HANDLE()
    need(bool(adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, c.byref(token))))
    try:
        size = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, c.byref(size))
        need(0 < size.value <= 65536)
        buffer = c.create_string_buffer(size.value)
        need(bool(adv.GetTokenInformation(token, 1, buffer, size.value, c.byref(size))))
        current = sid_text(ptr.from_buffer(buffer).value)
    finally: kernel.CloseHandle(token)

    owner, dacl, descriptor = ptr(), ptr(), ptr()
    error = adv.GetNamedSecurityInfoW(str(path), 1, 5, c.byref(owner), None,
                                     c.byref(dacl), None, c.byref(descriptor))
    try:
        need(error == 0 and bool(owner.value) and bool(dacl.value))
        class ACLSize(c.Structure):
            _fields_ = [('count', w.DWORD), ('used', w.DWORD), ('free', w.DWORD)]
        class ACEHeader(c.Structure):
            _fields_ = [('kind', w.BYTE), ('flags', w.BYTE), ('size', w.WORD)]
        size = ACLSize()
        need(bool(adv.GetAclInformation(dacl, c.byref(size), c.sizeof(size), 2)))
        need(0 < size.count <= 128)
        entries = []
        for index in range(size.count):
            ace = ptr(); need(bool(adv.GetAce(dacl, index, c.byref(ace))))
            header = c.cast(ace, c.POINTER(ACEHeader)).contents
            need(header.kind in (0, 1) and header.size >= 16)
            mask = c.cast(ace.value + 4, c.POINTER(w.DWORD)).contents.value
            entries.append((int(header.kind), int(mask), sid_text(ace.value + 8), int(header.flags)))
        validate_acl(sid_text(owner.value), current, entries)
    finally:
        if descriptor.value: kernel.LocalFree(descriptor)
