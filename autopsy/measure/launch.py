from __future__ import annotations

from dataclasses import dataclass

# A fixed, minimal base environment. Everything ambient is discarded so the
# stack base is identical between baseline and variant runs.
_BASE = {"PATH": "/usr/bin", "HOME": "/nonexistent", "LANG": "C"}


@dataclass(frozen=True)
class LaunchConfig:
    cpu: int = 2          # even CPUs only: siblings are (0,1) (2,3) ...
    aslr: bool = False    # False means -R, i.e. randomisation DISABLED
    env_bytes: int = 4096


def normalised_env(cfg: LaunchConfig = LaunchConfig()) -> dict:
    """Produce an environment block of exactly cfg.env_bytes bytes.

    Size is what matters, not content: it sets the initial stack pointer and
    therefore every stack object's alignment (Mytkowicz et al., ASPLOS 2009).
    """
    env = dict(_BASE)
    used = sum(len(k) + len(v) + 2 for k, v in env.items())
    need = cfg.env_bytes - used - len("PAD") - 2
    if need < 0:
        raise ValueError(
            f"env_bytes={cfg.env_bytes} is too small for the base environment "
            f"({used} bytes)")
    env["PAD"] = "X" * need
    return env


def build_command(argv: list[str], cfg: LaunchConfig = LaunchConfig()) -> list[str]:
    """Wrap argv with core pinning and ASLR control. All unprivileged."""
    cmd = ["taskset", "-c", str(cfg.cpu), "setarch"]
    if not cfg.aslr:
        cmd.append("-R")
    cmd.extend(argv)
    return cmd
