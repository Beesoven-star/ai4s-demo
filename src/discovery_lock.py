"""Small nonblocking OS lock, released even when its process crashes."""

import os
from pathlib import Path


class FileLock:
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        if not self.acquire():
            raise BlockingIOError("已有采集进程正在执行，请等待完成")
        return self

    def __exit__(self, *_):
        self.close()


def execution_lock_path(db_path):
    path = Path(db_path).resolve()
    return path.with_suffix(path.suffix + ".execution.lock")
