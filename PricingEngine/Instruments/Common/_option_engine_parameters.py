from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionEngineParameters:
    """
    Canonical, ergonomic container for engine selection + knobs.
    Use the class methods to create valid instances.

    kind:        'analytic' | 'fd' | 'tree' | 'baw' | 'bjerksund'
    nt, nx:      finite-difference grid sizes   (only for kind=='fd')
    steps:       binomial/trinomial steps       (only for kind=='tree')
    tree_method: 'jr'|'crr'|'tian'|'trigeorgis'|'lr'|'joshi' (only for 'tree')
    """

    kind: str
    nt: int | None = None
    nx: int | None = None
    steps: int | None = None
    tree_method: str | None = None

    # ---------- factories ----------
    @classmethod
    def analytic(cls) -> OptionEngineParameters:
        return cls(kind="analytic")

    @classmethod
    def fd(cls, nt: int = 200, nx: int = 400) -> OptionEngineParameters:
        if nt <= 0 or nx <= 0:
            raise ValueError("FD grid sizes must be positive")
        return cls(kind="fd", nt=nt, nx=nx)

    @classmethod
    def tree(cls, method: str = "lr", steps: int = 501) -> OptionEngineParameters:
        if steps <= 2:
            raise ValueError("tree steps must be > 2")
        method = method.lower()
        if method not in {"jr", "crr", "tian", "trigeorgis", "lr", "joshi"}:
            raise ValueError("tree_method must be one of jr, crr, tian, trigeorgis, lr, joshi")
        return cls(kind="tree", steps=steps, tree_method=method)

    @classmethod
    def baw(cls) -> OptionEngineParameters:
        return cls(kind="baw")

    @classmethod
    def bjerksund(cls) -> OptionEngineParameters:
        return cls(kind="bjerksund")

    # ---------- helpers ----------
    def tree_tag(self, default: str | None = None) -> str:
        mapping = {
            "jr": "JR",
            "crr": "CRR",
            "tian": "Tian",
            "trigeorgis": "Trigeorgis",
            "lr": "LR",
            "joshi": "Joshi4",
        }
        if self.tree_method is None:
            if default is None:
                raise ValueError("tree_tag() requires tree_method to be set or default provided")
            return default
        return mapping[self.tree_method.lower()]

    # ---------- validation ----------
    def validate_for(self, style: str) -> None:
        """
        Ensure the engine choice is compatible with the option style.
        style: 'european' | 'euro_digital' | 'american' | 'bermudan'
        """
        k = self.kind
        style = style.lower()

        if k == "analytic":
            if style in {"american", "bermudan"}:
                # no closed-form analytic engine for these (in this codebase)
                raise ValueError("analytic engine not supported for American/Bermudan")
            return

        if k == "fd":
            if (self.nt is None) or (self.nx is None):
                raise ValueError("fd engine requires nt and nx")
            return

        if k == "tree":
            if style in {"european", "euro_digital"}:
                # not implemented
                raise ValueError("analytic engine not supported for european/euro_digital")
            if (self.steps is None) or (self.tree_method is None):
                raise ValueError("tree engine requires steps and tree_method")
            return

        if k in {"baw", "bjerksund"}:
            if style != "american":
                raise ValueError(f"{k} engine only supported for American options")
            return

        raise ValueError(f"unknown engine kind: {k}")
