"""Cross-process write guard for small local JSON evidence stores."""
from contextlib import contextmanager
import os


@contextmanager
def write_lock(root, thread_lock):
    """Fail explicitly on a competing writer rather than losing an update.

    Keep the lock file after release: unlinking it could let another process
    lock a different inode while the original lock is still held.
    """
    with thread_lock:
        with (root / ".write.lock").open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            acquired = False
            try:
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError as exc:
                    raise ValueError("资料正由另一个 Formatly 进程更新，请稍后重试") from exc
                yield
            finally:
                if acquired:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
