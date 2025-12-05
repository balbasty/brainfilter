"""
A Path class that can be inherited from.

`pathlib.Path` cannot be directly inherited from because its `__new__`
method returns instances of different classes depending on the operating
system.

Instead, a concrete `PathLike` implementation is wrapped inside this class.
"""
import csv
import json
import gzip
import os
import shutil
import warnings
from collections.abc import MutableMapping, Mapping
from io import TextIOWrapper
from os import PathLike, stat_result
from typing import \
    Any, Callable, IO, Iterator, Literal, TYPE_CHECKING, overload

from brainfilter.tracking import TrackedMixin, TrackedLeaf, track

if TYPE_CHECKING:
    from pandas import DataFrame

try:
    from upath import UPath
    Path = UPath
except ImportError:
    UPath = None
    from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None


BasePath = UPath or PathLike
StrOrBytes = str | bytes
StrOrBytesOrPath = StrOrBytes | PathLike | BasePath
FileLike = StrOrBytesOrPath | IO
TextFileLike = StrOrBytesOrPath | IO[str]
BinaryFileLike = StrOrBytesOrPath | IO[bytes]


# ======================================================================
#
#                       S N I F F E R   M I X I N
#
# ======================================================================


class SnifferMixin:

    # --- file type sniffers -------------------------------------------

    def is_gzipped(self, sniff: bool | None = None) -> bool:
        if self.is_dir():
            return False
        check_ext = self._path.suffix.lower() == ".gz"
        if sniff or (sniff is None and not check_ext and self.exists()):
            try:
                with self.open("rb", compression=None) as f:
                    magic_number = f.read(2)
                return magic_number == b"\x1f\x8b"
            except Exception:
                return False
        return check_ext

    def is_json(self, sniff: bool | None = None) -> bool:
        if self.is_dir():
            return False
        suffixes = list(map(str.lower, self._path.suffixes[-2:]))
        check_ext = ".json" in suffixes
        if sniff or (sniff is None and not check_ext and self.exists()):
            try:
                with self.open("r", encoding="utf-8") as f:
                    json.load(f)
                return True
            except Exception:
                return False
        return check_ext

    def is_tsv(self, sniff: bool | None = None) -> bool:
        return self.is_xsv(
            sniff=sniff,
            delimiter="\t",
            extension=".tsv",
        )

    def is_csv(self, sniff: bool | None = None) -> bool:
        return self.is_xsv(
            sniff=sniff,
            delimiter=",",
            extension=".csv",
        )

    @overload
    def is_xsv(
        self,
        sniff: bool | None,
        delimiter: str | None,
        extension: str | list[str] | None,
        return_dialect: Literal[False],
    ) -> bool:
        ...

    @overload
    def is_xsv(
        self,
        sniff: bool | None,
        delimiter: str | None,
        extension: str | list[str] | None,
        return_dialect: Literal[True]
    ) -> csv.Dialect:
        ...

    def is_xsv(
        self,
        sniff: bool | None = None,
        delimiter: str | None = None,
        extension: str | list[str] | None = None,
        return_dialect: bool = False,
    ) -> bool | csv.Dialect:
        if self.is_dir():
            return False
        # Check extension first
        extension = extension or ([] if sniff else [".csv", ".tsv"])
        if isinstance(extension, str):
            extension = [extension]
        extension = list(map(str.lower, extension))
        suffixes = list(map(str.lower, self._path.suffixes[-2:]))
        extension = tuple(ext for ext in extension if ext in suffixes)
        check_ext = any(extension)
        if return_dialect and check_ext:
            extension = next(iter(extension))
            check_ext = {
                ".csv": NaiveCSVDialect(),
                ".tsv": NaiveTSVDialect(),
            }.get(extension, NaiveDialect)()

        # Now sniff if needed
        if sniff or (sniff is None and not check_ext and self.exists()):
            try:
                with self.open("r", encoding="utf-8") as f:
                    dialect = csv.Sniffer().sniff(f.read(1024))
                if delimiter not in (None, dialect.delimiter):
                    dialect = False
                return dialect if return_dialect else bool(dialect)
            except Exception:
                return False

        return check_ext


# ======================================================================
#
#                          F A N C Y   P A T H
#
# ======================================================================


class FancyPath(SnifferMixin, PathLike):
    """A wrapper around PathLike objects to provide Path-like behavior."""

    WrappedType = Path

    def __new__(cls, *args, **kwargs) -> "FancyPath":
        cls0 = cls
        path = FancyPath._make_pure(*args, **kwargs)
        if path.is_dir():
            if not issubclass(cls, FancyDirectory):
                cls = FancyDirectory
        elif path.is_json(sniff=False):
            if not issubclass(cls, FancyJSONFile):
                cls = FancyJSONFile
        elif path.is_tsv(sniff=False):
            if not issubclass(cls, FancyTSVFile):
                cls = FancyTSVFile
        elif path.is_csv(sniff=False):
            if not issubclass(cls, FancyCSVFile):
                cls = FancyCSVFile
        elif path.is_xsv(sniff=False):
            if not issubclass(cls, FancyXSVFile):
                cls = FancyXSVFile
        elif path.exists():
            if not issubclass(cls, FancyFile):
                cls = FancyFile
        obj = super().__new__(cls)
        if not issubclass(cls, cls0):
            obj.__init__(*args, **kwargs)
        return obj

    @classmethod
    def _make_pure(cls, *args, **kwargs) -> "FancyPath":
        obj = object.__new__(cls)
        obj.__init__(*args, **kwargs)
        return obj

    def __init__(self, *segments: StrOrBytesOrPath, **kwargs) -> None:
        super().__init__()
        segments = (
            seg._path if isinstance(seg, FancyPath) else seg
            for seg in segments
        )
        self._path = Path(*segments, **kwargs)
        self._content = None

    # ------------------------------------------------------------------
    # Additional methods and properties
    # ------------------------------------------------------------------

    # --- remove, whether file, link or dir ----------------------------

    def remove(
        self, missing_ok: bool = False, recursive: bool = True
    ) -> None:
        if self.is_dir():
            self.rmdir(recursive=recursive)
        else:
            self.unlink(missing_ok=missing_ok)

    # --- extension properties -----------------------------------------

    @property
    def extension(self) -> str:
        # Alias for suffix, as we will change the behavior of suffix
        # in the BIDS child class.
        return self._path.suffix

    @property
    def extensions(self) -> list[str]:
        # Alias for suffixes, as we will change the behavior of suffix
        # in the BIDS child class.
        return self._path.suffixes

    # ------------------------------------------------------------------
    # UPath interface
    # ------------------------------------------------------------------

    @property
    def fs(self) -> Any:
        if hasattr(self._path, "fs"):
            return self._path.fs
        return None

    def joinuri(self, uri: StrOrBytesOrPath) -> "FancyPath":
        if hasattr(self._path, "joinuri"):
            return self._path.joinuri(type(self)(uri))
        uri = self.from_uri(str(uri))
        return self.joinpath(uri)

    @property
    def path(self) -> str:
        if hasattr(self._path, "path"):
            return self._path.path
        return str(self._path)

    @property
    def protocol(self) -> str:
        if hasattr(self._path, "protocol"):
            return self._path.protocol
        return ""

    @property
    def storage_options(self) -> dict[str, Any]:
        if hasattr(self._path, "storage_options"):
            return self._path.storage_options
        return {}

    # ------------------------------------------------------------------
    # PathLike interface
    # ------------------------------------------------------------------

    def __fspath__(self) -> str:
        return self._path.__fspath__()

    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self._path)!r})"

    def __truediv__(self, key: StrOrBytesOrPath) -> "FancyPath":
        if self.is_file():
            return self[key]
        return type(self)(self._path / key)

    def __rtruediv__(self, key: StrOrBytesOrPath) -> "FancyPath":
        return type(self)(key / self._path)

    def absolute(self) -> "FancyPath":
        return type(self)(self._path.absolute())

    @property
    def anchor(self) -> str:
        return self._path.anchor

    def as_posix(self) -> str:
        return self._path.as_posix()

    def as_uri(self) -> str:
        return self._path.as_uri()

    def chmod(self, mode: int, *, follow_symlinks: bool = True) -> None:
        self._path.chmod(mode, follow_symlinks=follow_symlinks)

    def copy(
        self,
        target: StrOrBytesOrPath,
        follow_symlinks: bool = True,
        preserve_metadata: bool = False,
    ) -> "FancyPath":
        if hasattr(self._path, "copy"):
            return type(self)(self._path.copy(
                target,
                follow_symlinks=follow_symlinks,
                preserve_metadata=preserve_metadata
            ))

        copy = shutil.copy2 if preserve_metadata else shutil.copy
        if self.is_file():
            copy(self, target, follow_symlinks=follow_symlinks)
        else:
            shutil.copytree(
                self,
                target,
                symlinks=not follow_symlinks,
                copy_function=copy
            )
        return type(self)(target)

    def copy_into(
        self,
        target: StrOrBytesOrPath,
        follow_symlinks: bool = True,
        preserve_metadata: bool = False,
    ) -> "FancyPath":
        if hasattr(self._path, "copy_into"):
            return type(self)(self._path.copy_into(
                target,
                follow_symlinks=follow_symlinks,
                preserve_metadata=preserve_metadata
            ))

        return self.copy(
            type(self)(target) / self.name,
            follow_symlinks=follow_symlinks,
            preserve_metadata=preserve_metadata
        )

    def cwd(self) -> "FancyPath":
        return type(self)(self._path.cwd())

    @property
    def drive(self) -> str:
        return self._path.drive

    def exists(self) -> bool:
        return self._path.exists()

    def expanduser(self) -> "FancyPath":
        return type(self)(self._path.expanduser())

    @classmethod
    def from_uri(self, uri: str) -> "FancyPath":
        if hasattr(type(self)._path, "from_uri"):
            return type(self)(type(self)._path.from_uri(uri))
        raise NotImplementedError

    def full_match(
        self, pattern: str, *, case_sensitive: bool | None = None
    ) -> bool:
        if hasattr(self._path, "full_match"):
            return self._path.full_match(
                pattern,
                case_sensitive=case_sensitive
            )
        raise NotImplementedError

    def glob(self, pattern: str) -> Iterator["FancyPath"]:
        return (type(self)(p) for p in self._path.glob(pattern))

    def group(self) -> str:
        return self._path.group()

    def hardlink_to(self, target: StrOrBytesOrPath) -> None:
        self._path.hardlink_to(target)

    def home(self) -> "FancyPath":
        return type(self)(self._path.home())

    @property
    def info(self) -> None:
        raise NotImplementedError

    def is_absolute(self) -> bool:
        return self._path.is_absolute()

    def is_block_device(self) -> bool:
        return self._path.is_block_device()

    def is_char_device(self) -> bool:
        return self._path.is_char_device()

    def is_dir(self) -> bool:
        return self._path.is_dir()

    def is_fifo(self) -> bool:
        return self._path.is_fifo()

    def is_file(self) -> bool:
        return self._path.is_file()

    def is_junction(self) -> bool:
        if hasattr(self._path, "is_junction"):
            return self._path.is_junction()
        raise NotImplementedError

    def is_mount(self) -> bool:
        return self._path.is_mount()

    def is_relative_to(self, *other: StrOrBytesOrPath) -> bool:
        return self._path.is_relative_to(*other)

    def is_reserved(self) -> bool:
        return self._path.is_reserved()

    def is_socket(self) -> bool:
        return self._path.is_socket()

    def is_symlink(self) -> bool:
        return self._path.is_symlink()

    def iterdir(self) -> Iterator["FancyPath"]:
        return (type(self)(p) for p in self._path.iterdir())

    def joinpath(self, *args: StrOrBytesOrPath) -> "FancyPath":
        return type(self)(self._path.joinpath(*args))

    def lchmod(self, mode: int) -> None:
        self._path.lchmod(mode)

    def link_to(self, target: StrOrBytesOrPath) -> None:
        self._path.link_to(target)

    def lstat(self) -> stat_result:
        return self._path.lstat()

    def match(self, pattern: str) -> bool:
        return self._path.match(pattern)

    def mkdir(
        self,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        self._path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    def move(self, target: StrOrBytesOrPath) -> "FancyPath":
        if hasattr(self._path, "move"):
            return type(self)(self._path.move(target))
        try:
            self.replace(target)
        except Exception:
            self.copy(target, follow_symlinks=False, preserve_metadata=True)
            self.unlink()
        return type(self)(target)

    def move_into(self, target: StrOrBytesOrPath) -> "FancyPath":
        if hasattr(self._path, "move_into"):
            return type(self)(self._path.move_into(target))
        return self.move(type(self)(target) / self.name)

    @property
    def name(self) -> str:
        return self._path.name

    def open(
        self,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        compression: str | None = "auto",
    ) -> IO:
        if compression == "auto":
            if self.is_gzipped(sniff=True):
                compression = "gz"
            else:
                compression = None

        if "b" not in mode:
            mode += "t"

        if compression:
            true_mode, mode = mode, mode.replace("t", "b")
            true_newline, newline = newline, None
            true_encoding, encoding = encoding, None

        fileobj = self._path.open(
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )

        if compression == "gz":
            fileobj = GzipWrapper(
                fileobj=fileobj,
                mode=mode,
            )
        elif compression:
            raise ValueError(f"Unsupported compression type: {compression}")

        if compression and "t" in true_mode:
            fileobj = TextIOWrapper(
                buffer=fileobj,
                encoding=true_encoding,
                errors=errors,
                newline=true_newline,
            )

        return fileobj

    def owner(self) -> str:
        return self._path.owner()

    @property
    def parent(self) -> "FancyPath":
        return type(self)(self._path.parent)

    @property
    def parents(self) -> Iterator["FancyPath"]:
        for parent in self._path.parents:
            yield type(self)(parent)

    @property
    def parts(self) -> tuple[str, ...]:
        return self._path.parts

    def read_bytes(self) -> bytes:
        return self._path.read_bytes()

    def read_text(
        self,
        encoding: str | None = None,
        errors: str | None = None
    ) -> str:
        return self._path.read_text(encoding=encoding, errors=errors)

    def readlink(self) -> str:
        return self._path.readlink()

    def relative_to(self, *other: StrOrBytesOrPath) -> "FancyPath":
        return type(self)(self._path.relative_to(*other))

    def rename(self, target: StrOrBytesOrPath) -> "FancyPath":
        return type(self)(self._path.rename(target))

    def replace(self, target: StrOrBytesOrPath) -> "FancyPath":
        return type(self)(self._path.replace(target))

    def resolve(self, strict: bool = False) -> "FancyPath":
        return type(self)(self._path.resolve(strict=strict))

    def rglob(self, pattern: str) -> Iterator["FancyPath"]:
        return (type(self)(p) for p in self._path.rglob(pattern))

    def rmdir(self, recursive: bool = True) -> None:
        if issubclass(self.PathType, PathLike):
            # pathlib.Path only removes empty directories
            if recursive and self.is_dir():
                shutil.rmtree(self)
            else:
                self._path.rmdir()
        else:
            # UPath implements recursive removal
            self._path.rmdir(recursive)

    @property
    def root(self) -> "FancyPath":
        return type(self)(self._path.root)

    def samefile(self, other: StrOrBytesOrPath) -> bool:
        return self._path.samefile(other)

    def stat(self) -> stat_result:
        return self._path.stat()

    @property
    def stem(self) -> str:
        return self._path.stem

    @property
    def suffix(self) -> str:
        return self._path.suffix

    @property
    def suffixes(self) -> list[str]:
        return self._path.suffixes

    def symlink_to(
        self,
        target: StrOrBytesOrPath,
        target_is_directory: bool = False
    ) -> None:
        self._path.symlink_to(
            target,
            target_is_directory=target_is_directory
        )

    def touch(
        self,
        mode: int = 0o666,
        exist_ok: bool = True,
    ) -> None:
        self._path.touch(mode=mode, exist_ok=exist_ok)

    def unlink(self, missing_ok: bool = False) -> None:
        self._path.unlink(missing_ok=missing_ok)

    def walk(
        self,
        top_down: bool = True,
        on_error: Callable[[OSError], Any] | None = None,
        follow_symlinks: bool = False,
    ) -> Iterator[tuple["FancyPath", list[str], list[str]]]:
        if hasattr(self._path, "walk"):
            for dirpath, dirnames, filenames in self._path.walk(
                top_down=top_down,
                on_error=on_error,
                follow_symlinks=follow_symlinks
            ):
                yield type(self)(dirpath), dirnames, filenames
        else:
            for dirpath, dirnames, filenames in os.walk(
                self._path,
                topdown=top_down,
                onerror=on_error,
                followlinks=follow_symlinks
            ):
                yield type(self)(dirpath), dirnames, filenames

    def with_name(self, name: str) -> "FancyPath":
        return type(self)(self._path.with_name(name))

    def with_stem(self, stem: str) -> "FancyPath":
        return type(self)(self._path.with_stem(stem))

    def with_segments(self, *segments: list[str]) -> "FancyPath":
        return type(self)(*segments)

    def with_suffix(self, suffix: str) -> "FancyPath":
        return type(self)(self._path.with_suffix(suffix))

    def write_bytes(self, data: bytes) -> int:
        return self._path.write_bytes(data)

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None
    ) -> int:
        return self._path.write_text(data, encoding=encoding, errors=errors)


# ======================================================================
#
#                        M A P P I N G   M I X I N
#
# ======================================================================


class MappingMixin(MutableMapping):

    def to_dict(self) -> dict:
        """Convert the FancyPath to a dictionary representation."""
        return {
            key: (
                value.to_dict() if hasattr(value, "to_dict") else
                value.read() if hasattr(value, "read") else
                value
            )
            for key, value in self.items()
        }

    def __getitem__(self, key: StrOrBytes) -> "FancyPath":
        # Directory: return child path
        if self.is_dir():
            return type(self)(self / key)

        # We are within a context manager, read from in-memory content
        if self._content is not None:
            return self._content[key]

        # This is a file, read its content
        content = None

        for sniff in (False, True):

            # JSON file: read and return value
            if self.is_json(sniff=sniff):
                content = self._read_json()
                if not isinstance(content, Mapping):
                    raise TypeError("JSON file does not contain a dictionary.")
                break

            # CSV/TSV file: read and return column
            elif self.is_xsv(extension=[".csv", ".tsv"], sniff=sniff):
                if pd:
                    content = self._read_df()
                else:
                    content = self._read_xsv()
                break

        # Return tracked value
        if content is not None:
            content = track(content, self)
            return content[key]

        # Unsupported file type
        raise TypeError("File content is not a dictionary-like structure.")

    def __setitem__(self, key: StrOrBytes, value: Any) -> None:
        # Directory: copy file if PathLike, write content otherwise
        if self.is_dir():
            target_path = self / key
            if isinstance(value, PathLike):
                type(self)(value).copy(target_path, preserve_metadata=True)
            else:
                target_path.write(value)

        # We are within a context manager, modify in-memory content
        elif self._content is not None:
            self._content[key] = value

        # JSON file: read-modify-write
        elif self.is_json():
            content = self._read_json()
            if not isinstance(content, MutableMapping):
                raise TypeError("JSON file does not contain a dictionary.")
            content[key] = value
            self._write_json(content)

        # CSV/TSV file: read-modify-write
        elif self.is_xsv(extension=[".csv", ".tsv"]):
            if pd:
                df = self._read_df()
                df[key] = value
                self._write_df(df)
            else:
                table = self._read_xsv()
                table[key] = value
                self._write_dict_table(table)

        # Unsupported file type
        else:
            raise TypeError("File content is not a dictionary-like structure.")

    def __delitem__(self, key):
        # We are within a context manager, modify in-memory content
        if self._content is not None:
            del self._content[key]

        # Directory: remove child path
        elif self.is_dir():
            target_path = self / key
            try:
                target_path.remove()
            except FileNotFoundError as e:
                raise KeyError(e)

        # JSON file: read-modify-write
        elif self.is_json():
            content = self._read_json()
            if not isinstance(content, MutableMapping):
                raise TypeError("JSON file does not contain a dictionary.")
            del content[key]
            self._write_json(content)

        # CSV/TSV file: read-modify-write
        elif self.is_xsv(extension=[".csv", ".tsv"]):
            if pd:
                df = self._read_df()
                df = df.drop(columns=[key])
                self._write_df(df)
            else:
                table = self._read_xsv()
                del table[key]
                self._write_dict_table(table)

        # Unsupported file type
        else:
            raise TypeError("File content is not a dictionary-like structure.")

    def __len__(self) -> int:
        # We are within a context manager, return length of in-memory content
        if self._content is not None:
            return len(self._content)

        # Directory: number of child paths
        if self.is_dir():
            return sum(1 for _ in self.iterdir())

        # JSON file: number of keys
        if self.is_json():
            content = self._read_json()
            if not isinstance(content, Mapping):
                raise TypeError("JSON file does not contain a dictionary.")
            return len(content)

        # CSV/TSV file: number of columns
        if self.is_xsv(extension=[".csv", ".tsv"]):
            if pd:
                df = self._read_df()
                return len(df.columns)
            else:
                table = self._read_xsv()
                return len(table)

        # Unsupported file type
        return 0

    def __iter__(self) -> Iterator:
        # We are within a context manager, iterate over in-memory content
        if self._content is not None:
            yield from iter(self._content)

        # Directory: iterate over child path names
        elif self.is_dir():
            yield from (p.name for p in self.iterdir())

        # JSON file: iterate over keys
        elif self.is_json():
            content = self._read_json()
            if not isinstance(content, Mapping):
                return
            yield from iter(content)

        # CSV/TSV file: iterate over column names
        elif self.is_xsv(sniff=False):
            if pd:
                df = self._read_df()
                yield from iter(df.columns)
            else:
                table = self._read_xsv()
                yield from iter(table)

        # Unsupported file type
        return

    def __eq__(self, other):
        return FancyPath.__eq__(self, other)

    def __ne__(self, other):
        return FancyPath.__ne__(self, other)


# ======================================================================
#
#                     F A N C Y   D I R E C T O R Y
#
# ======================================================================


class FancyDirectory(MappingMixin, FancyPath):

    def __init__(self, *args, **kwargs) -> None:
        """
        Other Parameters
        ----------------
        if_missing : {'ignore', 'warn', 'raise', 'create', 'parents'}, default='ignore'
            Action to take if the directory does not exist.
            Options can be combined using '+'.
            * 'create' : Create the directory if it does not exist.
            * 'parents' : Create the parent directories if they do not exist.
            * 'warn' : Issue a warning if the directory does not exist.
            * 'raise' : Raise FileNotFoundError if the directory does not exist.
        if_exists : {'ignore', 'warn', 'raise', 'overwrite', 'iffile'}, default='ignore'
            Action to take if the directory already exists.
            Options can be combined using '+'.
            * 'overwrite' : Remove the existing file or directory and create a new one.
            * 'warn' : Issue a warning if the directory already exists.
            * 'raise' : Raise FileExistsError if the directory already exists.
            * 'iffile' : Take action only if a file with the same name exists.
        """  # noqa: E501
        if_missing = kwargs.pop("if_missing", "ignore")
        if_exists = kwargs.pop("if_exists", "ignore")
        super().__init__(*args, **kwargs)

        if not self.exists():

            msg = f"{self} does not exist."

            if "create" in if_missing:
                self.mkdir(parents="parent" in if_missing)

            elif "raise" in if_missing:
                raise FileNotFoundError(msg)

            elif "warn" in if_missing:
                warnings.warn(msg, UserWarning)

        elif (is_file := self.is_file()) or 'iffile' not in if_exists:

            msg = (
                f"A {'file' if is_file else 'directory'} named "
                f"{self} already exists."
            )

            if "overwrite" in if_exists:
                self.remove(recursive=True)

            elif "raise" in if_exists:
                raise FileExistsError(msg)

            elif "warn" in if_exists:
                warnings.warn(msg, UserWarning)


# ======================================================================
#
#                          F A N C Y   F I L E
#
# ======================================================================


class FancyFile(TrackedLeaf, FancyPath):

    def __init__(self, *args, **kwargs) -> None:
        """
        Other Parameters
        ----------------
        if_missing : {'ignore', 'warn', 'raise', 'create', 'parents'}, default='ignore'
            Action to take if the file does not exist.
            Options can be combined using '+'.
            * 'create' : Create the file if it does not exist.
            * 'parents' : Create the parent directories if they do not exist.
            * 'warn' : Issue a warning if the file does not exist.
            * 'raise' : Raise FileNotFoundError if the file does not exist.
        if_exists : {'ignore', 'warn', 'raise', 'overwrite', 'ifdir'}, default='ignore'
            Action to take if the file already exists.
            Options can be combined using '+'.
            * 'overwrite' : Remove the existing file or directory and create a new one.
            * 'warn' : Issue a warning if the file already exists.
            * 'raise' : Raise FileExistsError if the file already exists.
            * 'ifdir' : Take action only if a directory with the same name exists.
        """  # noqa: E501
        if_missing = kwargs.pop("if_missing", "ignore")
        if_exists = kwargs.pop("if_exists", "ignore")

        super().__init__(*args, **kwargs)

        if not self.exists():
            msg = f"{self} does not exist."

            if "create" in if_missing:
                if "parents" in if_missing:
                    self.parent.mkdir(parents=True)
                self.touch()

            elif "raise" in if_missing:
                raise FileNotFoundError(msg)

            elif "warn" in if_missing:
                warnings.warn(msg, UserWarning)

        elif (is_dir := self.is_dir()) or 'ifdir' not in if_exists:

            msg = (
                f"A {'directory' if is_dir else 'file'} named "
                f"{self} already exists."
            )

            if "overwrite" in if_exists:
                self.remove()

            elif "raise" in if_exists:
                raise FileExistsError(msg)

            elif "warn" in if_exists:
                warnings.warn(msg, UserWarning)

    # --- context manager ----------------------------------------------

    @property
    def content(self) -> Any:
        """Get the in-memory content of the file."""
        if self._content is None:
            self.load()
        return self._content

    def __enter__(self) -> "FancyPath":
        self.load()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any
    ) -> None:
        if exc_type is None and self._content is not None:
            self.dump()
        self._content = None

    def load(self) -> None:
        """Load the content of the file into memory."""
        if self.is_file():
            self._content = self.read()

    def dump(self) -> None:
        """Write the in-memory content back to the file."""
        if self._content is not None:
            self.write(self._content)

    # --- tracking utility for smart read/write ------------------------

    def _changed(self, child: TrackedMixin) -> None:
        self.write(child)

    # --- smart readers ------------------------------------------------

    def read(self) -> Any:
        for sniff in (False, True):
            if self.is_json(sniff=sniff):
                return self._read_json()
            elif self.is_xsv(extension=[".csv", ".tsv"], sniff=sniff):
                if pd:
                    return self._read_df()
                else:
                    return self._read_xsv()
        return self._read_text()

    def _read_json(self) -> dict:
        with self.open('r', encoding='utf-8') as src_file:
            return json.load(src_file)

    def _read_df(self) -> "DataFrame":
        if not pd:
            raise ImportError(
                "pandas is required to read DataFrame from file."
            )
        return pd.read_csv(self._path)

    def _read_xsv(self, **kwargs) -> dict[str, list]:
        table = {}
        with self.open('r', encoding='utf-8') as src_file:
            reader = csv.DictReader(src_file, **kwargs)
            for row in reader:
                nval = len(next(iter(table.values()), []))
                for key, value in row.items():
                    table.setdefault(key, [None] * nval)
                    table[key].append(value)
                for key in table.keys():
                    if key not in row:
                        table[key].append(None)
        return table

    def _read_text(self) -> str:
        with self.open('r', encoding='utf-8') as src_file:
            return src_file.read()

    def _read_bytes(self) -> bytes:
        with self.open('rb') as src_file:
            return src_file.read()

    # --- smart writers ------------------------------------------------

    def write(self, value: Any) -> None:
        if isinstance(value, Mapping):
            self._write_dict(value)
        elif pd and isinstance(value, pd.DataFrame):
            self._write_df(value)
        elif isinstance(value, str):
            self._write_text(value)
        elif isinstance(value, (bytes, bytearray, memoryview)):
            self._write_bytes(value)
        elif hasattr(value, "read"):
            self._write_filelike(value)
        else:
            raise TypeError(f"Unsupported value type: {type(value)}")

    def _write_filelike(self, value: IO) -> None:
        with self.open('wb') as dst_file:
            dst_file.write(value.read())

    def _write_text(self, value: str) -> None:
        with self.open('w', encoding='utf-8') as dst_file:
            dst_file.write(value)

    def _write_bytes(self, value: bytes | bytearray | memoryview) -> None:
        with self.open('wb') as dst_file:
            if isinstance(value, bytes):
                dst_file.write(value)
            else:
                dst_file.write(value.tobytes())

    def _write_json(self, value: dict) -> None:
        with self.open('w', encoding='utf-8') as dst_file:
            json.dump(value, dst_file, indent=4)

    def _write_dict(self, value: dict) -> None:
        # If we know that the file is JSON, write as JSON
        if self.is_json(sniff=True):
            self._write_json(value)
            return

        # If we know that the file is CSV or TSV, write as such
        dialect = self.is_xsv(return_dialect=True)
        if dialect:
            self._write_dict_table(value, delimiter=dialect.delimiter)
            return

        # Otherwise, default to JSON
        self._write_json(value)

    def _write_dict_table(
        self,
        value: dict[str, list],
        delimiter: str | None = None,
        **kwargs
    ) -> None:
        if not value:
            raise ValueError("Cannot write empty dictionary to CSV/TSV.")
        if delimiter is None:
            delimiter = '\t' if self.is_tsv() else ','

        if isinstance(value, Mapping):
            # Convert dict[str, list] to iterator[dict]
            keys = list(value.keys())
            nrows = len(next(iter(value.values())))
            value = (
                {key: value[key][i] for key in keys}
                for i in range(nrows)
            )

        rows = iter(value)
        first_row = next(rows)
        with self.open('w', encoding='utf-8') as dst_file:
            writer = csv.DictWriter(
                dst_file,
                fieldnames=list(first_row.keys()),
                delimiter=delimiter,
                **kwargs
            )
            writer.writeheader()
            writer.writerow(first_row)
            writer.writerows(rows)
        return

    def _write_df(
        self,
        value: "DataFrame",
        delimiter: str | None = None,
        **kwargs
    ) -> None:
        if delimiter is None:
            delimiter = '\t' if self.is_tsv() else ','
        value.to_csv(self, index=False, sep=delimiter, **kwargs)


# ======================================================================
#
#                F A N C Y   M A P P I N G   F I L E S
#
# ======================================================================


class FancyMappingFile(MappingMixin, FancyFile):
    ...


class FancyXSVFile(FancyMappingFile):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not self.is_xsv():
            raise TypeError(f"{self} is not a CSV/TSV file.")


class FancyCSVFile(FancyXSVFile):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not self.is_csv():
            raise TypeError(f"{self} is not a CSV file.")


class FancyTSVFile(FancyXSVFile):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not self.is_tsv():
            raise TypeError(f"{self} is not a TSV file.")


class FancyJSONFile(FancyMappingFile):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not self.is_json():
            raise TypeError(f"{self} is not a JSON file.")


# ======================================================================
#
#                        I / O   W R A P P E R S
#
# ======================================================================


class GzipWrapper(gzip.GzipFile):
    # Calling a GzipFile object’s close() method does not close fileobj,
    # since you might wish to append more material after the compressed data.
    #
    # We override close() to also close the underlying file object.

    def __init__(self, fileobj, *args, **kwargs) -> None:
        super().__init__(None, *args, **kwargs, fileobj=fileobj)

    def close(self):
        super().close()
        if getattr(self, 'fileobj', None):
            self.fileobj.close()


# ======================================================================
#
#                        C S V   D I A L E C T S
#
# ======================================================================


class NaiveDialect(csv.Dialect):
    delimiter = ','
    doublequote = True
    escapechar = None
    lineterminator = '\n'
    quotechar = '"'
    quoting = csv.QUOTE_MINIMAL
    skipinitialspace = False


class NaiveCSVDialect(NaiveDialect):
    delimiter = ','


class NaiveTSVDialect(NaiveDialect):
    delimiter = '\t'
