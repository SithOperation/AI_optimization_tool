"""Windows generic credentials, scoped to the current Windows user."""
import ctypes
from ctypes import wintypes
import os
import re


class Credential(ctypes.Structure):
    _fields_ = [("Flags",wintypes.DWORD),("Type",wintypes.DWORD),("TargetName",wintypes.LPWSTR),
                ("Comment",wintypes.LPWSTR),("LastWritten",wintypes.FILETIME),
                ("CredentialBlobSize",wintypes.DWORD),("CredentialBlob",ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist",wintypes.DWORD),("AttributeCount",wintypes.DWORD),("Attributes",ctypes.c_void_p),
                ("TargetAlias",wintypes.LPWSTR),("UserName",wintypes.LPWSTR)]


class WindowsCredentials:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows Credential Manager is unavailable")
        self.api = ctypes.WinDLL("Advapi32", use_last_error=True)
        pointer = ctypes.POINTER(Credential)
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(pointer)]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredWriteW.argtypes = [pointer,wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD]
        self.api.CredDeleteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredFree.restype = None

    def target(self, reference):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", reference):
            raise ValueError("Invalid credential reference")
        return "AIOptimizationTool/" + reference

    def get(self, reference):
        pointer = ctypes.POINTER(Credential)()
        if not self.api.CredReadW(self.target(reference),1,0,ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise OSError("Credential Manager read failed")
        try:
            return ctypes.string_at(pointer.contents.CredentialBlob,pointer.contents.CredentialBlobSize).decode("utf-8")
        finally:
            self.api.CredFree(pointer)

    def set(self, reference, value):
        encoded = value.encode("utf-8")
        if not encoded or len(encoded) > 2560:
            raise ValueError("Credential must contain between 1 and 2560 UTF-8 bytes")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = Credential(Type=1,TargetName=self.target(reference),CredentialBlobSize=len(encoded),
                                CredentialBlob=blob,Persist=2,UserName="AIOptimizationTool")
        try:
            if not self.api.CredWriteW(ctypes.byref(credential),0):
                raise OSError("Credential Manager write failed")
        finally:
            ctypes.memset(blob,0,len(encoded))

    def delete(self, reference):
        if not self.api.CredDeleteW(self.target(reference),1,0) and ctypes.get_last_error() != 1168:
            raise OSError("Credential Manager deletion failed")
