"""Stand-ins: each built-in one recognised from what its tool keeps in a file's place,
committed in a real repository, and another package's, registered in the entry-point group
`astra.standins`."""

from __future__ import annotations

from pathlib import Path

import pytest

from astra import api
from astra._internal.sources.git import Repository
from astra._internal.sources.reader import CommitReader, WorktreeReader
from astra._internal.sources.remote import Remotes
from astra._internal.sources.standins import (
    BUILT_IN,
    Dvc,
    Found,
    GitAnnex,
    GitLfs,
    look,
    registered,
)
from tests.conftest import MINIMAL, repository

ANNEXED = "SHA256E-s6--" + "5" * 64 + ".bin"
"""A git-annex key: a SHA-256 backend, the size, the hash and the extension."""

LFS_POINTER = f"version https://git-lfs.github.com/spec/v1\noid sha256:{'a' * 64}\nsize 6\n"

DVC_FILE = "outs:\n- md5: 0cc175b9c0f1b6a831c399e269772661\n  size: 6\n  hash: md5\n  path: {}\n"


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> WorktreeReader:
    files = {
        "lfs.bin": LFS_POINTER,
        "lfs-no-size.bin": LFS_POINTER.replace("size 6\n", ""),
        "unlocked.bin": f"/annex/objects/{ANNEXED}\n",
        "plain.csv": "a,b\n1,2\n",
        "huge.csv.dvc": DVC_FILE.format("huge.csv"),
    }
    top = repository(tmp_path_factory.mktemp("tree"), {})
    (top / "locked.bin").symlink_to(f".git/annex/objects/Jx/3M/{ANNEXED}/{ANNEXED}")
    (top / "link.csv").symlink_to("plain.csv")
    repository(top, files)
    return WorktreeReader(top, Repository(top))


def test_git_lfs_recognises_its_pointer_file(tree: WorktreeReader) -> None:
    """`version`, then `oid sha256:…` and `size …`, at the path itself."""
    assert GitLfs().recognises(tree, "lfs.bin")
    assert GitLfs().place("lfs.bin") == "lfs.bin"
    assert not GitLfs().recognises(tree, "lfs-no-size.bin")
    assert not GitLfs().recognises(tree, "plain.csv")
    assert not GitLfs().recognises(tree, "nothere.bin")


def test_git_annex_recognises_a_symlink_or_a_pointer_into_its_objects(
    tree: WorktreeReader,
) -> None:
    """A locked file, committed as a symlink into `annex/objects/`, whose target needn't be there,
    and an unlocked pointer file; never another symlink or file."""
    assert GitAnnex().recognises(tree, "locked.bin")
    assert GitAnnex().recognises(tree, "unlocked.bin")
    assert not GitAnnex().recognises(tree, "link.csv")
    assert not GitAnnex().recognises(tree, "plain.csv")


def test_dvc_recognises_its_file_beside_the_path(tree: WorktreeReader) -> None:
    """`<path>.dvc` beside a path that names nothing, which is what git tracks."""
    assert Dvc().place("huge.csv") == "huge.csv.dvc"
    assert Dvc().recognises(tree, "huge.csv")
    assert not Dvc().recognises(tree, "plain.csv")


def test_each_gives_the_hash_and_size_of_what_it_stands_for_where_it_can(
    tree: WorktreeReader,
) -> None:
    """What each stand-in gives, which the checker compares as an input's content: a Git LFS
    pointer's `oid` and `size`, a git-annex key of a SHA-256 backend, and nothing of a DVC file,
    whose hash is an MD5."""
    assert GitLfs().gives(tree, "lfs.bin") == (f"sha256:{'a' * 64}", 6)
    assert GitLfs().gives(tree, "plain.csv") is None
    assert GitAnnex().gives(tree, "locked.bin") == (f"sha256:{'5' * 64}", 6)
    assert GitAnnex().gives(tree, "unlocked.bin") == (f"sha256:{'5' * 64}", 6)
    assert Dvc().gives(tree, "huge.csv") is None


def test_each_says_where_the_content_is_on_disk(tmp_path: Path) -> None:
    """A git-annex link leads to the content once it is fetched, and DVC puts it at the path
    beside its file. A pointer file is there only while the content isn't. At a commit, the
    tree isn't on disk, and a tool's store is the tool's to read."""
    files = {
        "lfs.bin": LFS_POINTER,
        "unlocked.bin": f"/annex/objects/{ANNEXED}\n",
        "huge.csv.dvc": DVC_FILE.format("huge.csv"),
    }
    top = repository(tmp_path, files)
    kept = top / ".git" / "annex" / "objects" / "Jx" / "3M" / ANNEXED / ANNEXED
    (top / "locked.bin").symlink_to(kept.relative_to(top))
    repository(top, {})
    reader = WorktreeReader(top, Repository(top))
    assert GitLfs().content(reader, "lfs.bin") is None
    assert GitAnnex().content(reader, "unlocked.bin") is None
    assert GitAnnex().content(reader, "locked.bin") is None
    assert Dvc().content(reader, "huge.csv") is None
    assert look(reader, "locked.bin", BUILT_IN) == Found(False, GitAnnex())

    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"binary")
    (top / "huge.csv").write_text("a,b\n")
    reader = WorktreeReader(top, Repository(top))
    assert GitAnnex().content(reader, "locked.bin") == kept
    assert Dvc().content(reader, "huge.csv") == top / "huge.csv"
    assert look(reader, "locked.bin", BUILT_IN) == Found(True, GitAnnex(), kept)
    assert look(reader, "huge.csv.dvc", BUILT_IN) == Found(True)
    assert look(reader, "nothing.bin", BUILT_IN) == Found()
    head = Repository(top).head()
    assert head is not None
    at_commit = CommitReader(Repository(top), head, None, Remotes())
    assert GitAnnex().recognises(at_commit, "locked.bin")
    assert GitAnnex().content(at_commit, "locked.bin") is None


def test_a_git_annex_link_is_followed_to_a_store_outside_the_tree(tmp_path: Path) -> None:
    """In a submodule or a linked worktree, `.git` is itself a link, and the object store is
    outside the tree: the link is followed as the operating system follows it, and its
    content is here."""
    store = tmp_path / "parent" / ".git" / "modules" / "sub"
    kept = store / "annex" / "objects" / "Jx" / "3M" / ANNEXED / ANNEXED
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"binary")
    top = repository(tmp_path / "sub", {"keep": ""})
    (top / "gitdir").symlink_to(store)
    (top / "locked.bin").symlink_to(f"gitdir/annex/objects/Jx/3M/{ANNEXED}/{ANNEXED}")
    reader = WorktreeReader(top, Repository(top))
    assert look(reader, "locked.bin", BUILT_IN) == Found(True, GitAnnex(), kept)


def test_a_link_dressed_as_git_annexs_that_leads_elsewhere_isnt_followed(tmp_path: Path) -> None:
    """A git-annex link is relative and names a file in an `annex/objects` folder of the
    tree; and what it leads to really is in one. A link that goes above the top, or is
    absolute, is no stand-in. One whose `annex/objects` is itself a link to some other folder
    is, and its content isn't here: the file it leads to is in no object store."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("secret")
    top = repository(tmp_path / "repo", {"decoy/annex/keep": ""})
    (top / "above.bin").symlink_to("decoy/annex/objects/../../../../outside/secret")
    (top / "absolute.bin").symlink_to(outside / "secret")
    (top / "decoy" / "annex" / "objects").symlink_to(outside)
    (top / "dressed.bin").symlink_to("decoy/annex/objects/secret")
    reader = WorktreeReader(top, Repository(top))
    assert (top / "dressed.bin").read_text() == "secret"
    assert look(reader, "above.bin", BUILT_IN) == Found()
    assert look(reader, "absolute.bin", BUILT_IN) == Found()
    assert look(reader, "dressed.bin", BUILT_IN) == Found(False, GitAnnex())


def test_what_is_beside_a_dvc_file_is_followed_wherever_it_leads(tmp_path: Path) -> None:
    """DVC links a file from its cache, which can be anywhere: outside the repository too."""
    cache = tmp_path / "shared-cache" / "files" / "md5" / "0c"
    cache.mkdir(parents=True)
    (cache / "c175b9c0f1b6a831c399e269772661").write_text("a,b\n")
    top = repository(tmp_path / "repo", {"huge.csv.dvc": DVC_FILE.format("huge.csv")})
    (top / "huge.csv").symlink_to(cache / "c175b9c0f1b6a831c399e269772661")
    reader = WorktreeReader(top, Repository(top))
    kept = cache / "c175b9c0f1b6a831c399e269772661"
    assert look(reader, "huge.csv", BUILT_IN) == Found(True, Dvc(), kept)
    # A link with no DVC file beside it is no stand-in, and is followed nowhere.
    (top / "plain.csv").symlink_to(kept)
    assert look(reader, "plain.csv", BUILT_IN) == Found()


class Counting(WorktreeReader):
    """A working tree that keeps how much of each file is asked for."""

    def read(self, path: str, limit: int | None = None) -> bytes:
        READ.append((path, limit))
        return super().read(path, limit)


READ: list[tuple[str, int | None]] = []


def test_a_file_too_long_to_be_a_pointer_isnt_read_to_see(tmp_path: Path) -> None:
    """Each stand-in looks at a file's first kilobyte and no more, so a result of gigabytes
    costs what a small one does."""
    top = repository(tmp_path, {"big.bin": "x" * 100_000, "lfs.bin": LFS_POINTER})
    reader = Counting(top, Repository(top))
    READ.clear()
    assert look(reader, "big.bin", BUILT_IN) == Found(True)
    assert READ and all(path == "big.bin" and limit == 1025 for path, limit in READ)
    assert reader.read("big.bin", 4) == b"xxxx" and len(reader.read("big.bin")) == 100_000
    assert look(reader, "lfs.bin", BUILT_IN) == Found(False, GitLfs())


PLUGIN = """\
from dataclasses import dataclass


@dataclass(frozen=True)
class Store:
    name: str = "store"

    def place(self, path):
        return path

    def recognises(self, reader, path):
        entry = reader.stat(path)
        return entry is not None and entry.kind == "symlink" and entry.target.startswith("store/")

    def gives(self, reader, path):
        return None

    def content(self, reader, path):
        return None


STANDIN = Store()
"""


def test_another_package_registers_a_stand_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An object in the entry-point group `astra.standins` is recognised after the built-in ones,
    and keeps `MISSING_INPUT_FILE` for what it stands in for."""
    top = repository(tmp_path / "repo", {"store/x": "1\n"})
    (top / "data.raw").symlink_to("store/x")
    repository(top, {"astra.yaml": MINIMAL + "inputs:\n  raw: {path: data.raw}\n"})
    assert [d.code for d in api.validate(top).diagnostics] == ["MISSING_INPUT_FILE"]

    plugin = tmp_path / "plugin"
    (plugin / "astra_test_standin-0.dist-info").mkdir(parents=True)
    (plugin / "astra_test_standin.py").write_text(PLUGIN)
    (plugin / "astra_test_standin-0.dist-info" / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: astra-test-standin\nVersion: 0\n"
    )
    (plugin / "astra_test_standin-0.dist-info" / "entry_points.txt").write_text(
        "[astra.standins]\nstore = astra_test_standin:STANDIN\n"
    )
    monkeypatch.syspath_prepend(str(plugin))
    assert [standin.name for standin in registered()] == [
        *(standin.name for standin in BUILT_IN),
        "store",
    ]
    assert api.validate(top).diagnostics == ()
