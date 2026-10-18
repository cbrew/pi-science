"""The discovered conventions of the CGEL treebank, as machine-readable tables.

These tables are the *grammar of the treebank* used by:

* ``cgel_conventions.py`` -- a strict conformance checker (reports the four
  known annotator-flagged deviations when using ``STRICT`` tables);
* ``cgel_models.py`` -- probability models over analyses: Model A (labels
  independent) and Model B (support = convention-conforming analyses only).

Two views of the tables exist:

* ``XBAR_STRICT`` / strict tables -- the projection skeleton as stated in
  docs/cgel-conventions.md (verified against the corpus: 5566 Head edges,
  0 head-rule violations; 4 X-bar deviations exist, all annotated with notes);
* ``XBAR_ALLOWED`` / ``HEAD_ALLOWED`` / ``EDGE_PARENTS`` / ``EDGE_CHILDREN``
  -- the *complete observed* regime (the four flagged X-bar items added),
  used as the generative license set for the models.

``allowed(parent_cat, edge, child)`` decides whether an edge between a parent
with category ``parent_cat`` and a child labelled ``(edge, child.cat)`` is
licensed by the conventions.  ``ROOT`` is a sentinel used for the root node.
"""
from typing import Dict, FrozenSet, Set

ROOT = "<ROOT>"

# --------------------------------------------------------------------------
# root: only these categories may head a whole analysis (observed)
# --------------------------------------------------------------------------
ROOT_CATS: Set[str] = {"Clause", "Coordination", "NP", "VP", "Nom", "AdjP"}

# categories that can be assigned to a *variable* (structural) node: every
# phrase-level category that ever occurs, incl. fused coordination labels
PHRASE_CATS: Set[str] = {
    "Clause", "Clause_rel", "VP", "NP", "Nom", "DP", "PP", "PP_strand",
    "AdjP", "AdvP", "IntP", "Coordination",
    "NP+PP", "NP+AdvP", "NP+AdjP", "NP+Clause",
}
# word-level categories (leaves; a few can be flat containers for names)
WORD_CATS: Set[str] = {
    "N", "N_pro", "V", "V_aux", "P", "D", "Adj", "Adv",
    "Coordinator", "Sdr", "Int",
}
ALL_CATS: Set[str] = PHRASE_CATS | WORD_CATS | {"GAP"}

# --------------------------------------------------------------------------
# all function (edge) labels observed
# --------------------------------------------------------------------------
EDGES: Set[str] = {
    "Head", "Mod", "Obj", "Comp", "Det", "Subj", "Coordinate", "Marker",
    "Supplement", "PredComp", "Flat", "Det-Head", "Prenucleus", "Postnucleus",
    "DisplacedSubj", "Comp_ind", "Particle", "Obj_ind", "Obj_dir",
    "ExtraposedSubj", "Mod-Head", "Head-Prenucleus", "Vocative",
    "Compounding", "Obj+Mod", "Obj+PredComp/Comp", "Marker-Head",
}

# --------------------------------------------------------------------------
# 1. the XBAR / projection skeleton
# --------------------------------------------------------------------------
XBAR_STRICT: Dict[str, Set[str]] = {
    "Clause":        {"VP", "Clause", "NP", "PP", "AdvP", "AdjP", "V_aux",
                      "Coordinator", "Coordination", "Sdr", "GAP", "IntP",
                      "Clause_rel"},
    "Clause_rel":    {"VP", "NP", "Clause_rel", "GAP", "Sdr", "PP", "Coordination", "Clause"},
    "VP":            {"V", "V_aux", "VP", "Clause", "NP", "PP", "GAP", "Sdr",
                      "AdvP", "AdjP", "Coordination", "Coordinator", "PP_strand",
                      "DP", "IntP"},
    "NP":            {"Nom", "NP", "DP", "Coordinator", "Coordination", "AdvP",
                      "PP", "Clause_rel", "Clause", "AdjP", "VP", "GAP"},
    "Nom":           {"N", "N_pro", "Nom", "AdjP", "PP", "DP", "Clause_rel",
                      "Clause", "VP", "Coordinator", "Coordination", "NP", "GAP"},
    "PP":            {"P", "NP", "Clause", "PP", "Coordination", "AdvP", "AdjP",
                      "Coordinator", "GAP"},
    "PP_strand":     {"P", "GAP"},
    "DP":            {"D", "AdvP", "DP", "PP", "Coordination", "Coordinator"},
    "AdjP":          {"Adj", "AdjP", "AdvP", "PP", "Coordinator", "DP", "Clause", "GAP"},
    "AdvP":          {"Adv", "AdvP", "DP", "PP", "Coordinator", "NP"},
    "IntP":          {"Int"},
    "Coordination":  {"Clause", "NP", "VP", "Nom", "AdjP", "PP", "Coordinator",
                      "DP", "IntP", "Coordination", "NP+PP", "NP+AdvP",
                      "NP+AdjP", "NP+Clause"},
}
# the four annotator-flagged relaxations (documented in docs/cgel-conventions.md):
# combining-form -like (AdjP :Mod (NP)), medial adverb in nominal
# (Nom :Mod (AdvP)), stranded preposition complement in nominal
# (Nom :Comp (PP_strand))
XBAR_ALLOWED: Dict[str, Set[str]] = {
    k: set(v) for k, v in XBAR_STRICT.items()
}
XBAR_ALLOWED["AdjP"].add("NP")
XBAR_ALLOWED["Nom"] |= {"AdvP", "PP_strand"}

# --------------------------------------------------------------------------
# 2. the HEAD RULE
# --------------------------------------------------------------------------
HEAD_ALLOWED: Dict[str, Set[str]] = {
    "Clause":        {"VP", "Clause", "Coordination", "GAP"},
    "Clause_rel":    {"VP", "Clause_rel"},
    "VP":            {"V", "V_aux", "VP", "Coordination", "GAP"},
    "NP":            {"Nom", "NP", "Coordination", "GAP"},
    "Nom":           {"N", "N_pro", "Nom"},
    "PP":            {"P", "PP"},
    "PP_strand":     {"P"},
    "DP":            {"D", "DP", "Coordination"},
    "AdjP":          {"Adj", "AdjP"},
    "AdvP":          {"Adv", "AdvP"},
    "IntP":          {"Int"},
    "Coordination":  {"Coordination"},
    "NP+PP":         {"NP+PP"},
    "NP+AdvP":       {"NP+AdvP"},
    "NP+AdjP":       {"NP+AdjP"},
    "NP+Clause":     {"NP+Clause"},
}

# --------------------------------------------------------------------------
# 3. function -> parent  and  function -> child licensing (observed)
# --------------------------------------------------------------------------
EDGE_PARENTS: Dict[str, Set[str]] = {
    "Head": PHRASE_CATS | {"N", "D", "Coordination"},
    "Mod": {"Nom", "VP", "Clause", "AdjP", "NP", "PP", "AdvP", "DP",
            "NP+PP", "NP+AdvP"},
    "Obj": {"PP", "VP", "NP+PP", "PP_strand", "NP+AdvP", "NP+AdjP",
            "NP+Clause", "AdjP"},
    "Comp": {"VP", "PP", "Nom", "AdjP", "NP+Clause", "Clause"},
    "Det": {"NP"},
    "Subj": {"Clause", "Clause_rel"},
    "Coordinate": {"Coordination"},
    "Marker": {"VP", "Clause", "NP", "Nom", "AdjP", "Clause_rel", "PP",
               "NP+PP", "NP+Clause", "Coordination", "DP", "AdvP", "NP+AdvP"},
    "Supplement": {"Clause", "NP", "Nom", "VP", "PP", "Coordination",
                   "AdjP", "Clause_rel"},
    "PredComp": {"VP", "PP", "NP+AdjP"},
    "Flat": {"N", "D"},
    "Det-Head": {"Nom"},
    "Prenucleus": {"Clause", "Clause_rel"},
    "Postnucleus": {"Clause", "VP", "AdjP", "Nom"},
    "DisplacedSubj": {"VP"},
    "Comp_ind": {"Nom", "AdjP", "AdvP", "Clause"},
    "Particle": {"VP"},
    "Obj_ind": {"VP"},
    "Obj_dir": {"VP"},
    "ExtraposedSubj": {"VP"},
    "Mod-Head": {"Nom"},
    "Head-Prenucleus": {"Clause_rel"},
    "Vocative": {"Clause", "VP"},
    "Compounding": {"Nom"},
    "Obj+Mod": {"VP"},
    "Obj+PredComp/Comp": {"VP"},
    "Marker-Head": {"Nom"},
}

EDGE_CHILDREN: Dict[str, Set[str]] = {
    "Head": PHRASE_CATS | WORD_CATS | {"GAP", "Coordination"},
    "Mod": {"PP", "Nom", "AdvP", "AdjP", "Clause_rel", "GAP", "NP", "DP",
            "Clause", "Coordination", "VP"},
    "Obj": {"NP", "GAP", "Coordination"},
    "Comp": {"Clause", "PP", "Coordination", "GAP", "PP_strand", "AdjP", "NP"},
    "Det": {"DP", "NP", "PP"},
    "Subj": {"NP", "GAP", "Clause", "Coordination", "PP"},
    "Coordinate": PHRASE_CATS | {"Coordination", "Coordinator",
                                 "NP+PP", "NP+AdvP", "NP+AdjP", "NP+Clause"},
    "Marker": {"Coordinator", "Sdr", "DP"},
    "Supplement": {"NP", "PP", "Clause", "AdvP", "Clause_rel", "IntP",
                   "Coordination", "VP"},
    "PredComp": {"AdjP", "NP", "PP", "Coordination", "GAP", "Clause"},
    "Flat": {"N", "D"},
    "Det-Head": {"DP", "NP"},
    "Prenucleus": {"V_aux", "NP", "AdvP", "PP", "AdjP", "Clause", "VP"},
    "Postnucleus": {"NP", "Clause", "PP", "Coordination"},
    "DisplacedSubj": {"NP"},
    "Comp_ind": {"Clause", "PP"},
    "Particle": {"PP"},
    "Obj_ind": {"NP"},
    "Obj_dir": {"NP", "GAP"},
    "ExtraposedSubj": {"Clause"},
    "Mod-Head": {"AdjP", "PP", "VP"},
    "Head-Prenucleus": {"NP"},
    "Vocative": {"NP"},
    "Compounding": {"VP", "PP"},
    "Obj+Mod": {"Coordination"},
    "Obj+PredComp/Comp": {"Coordination"},
    "Marker-Head": {"Coordinator"},
}


# --------------------------------------------------------------------------
# the licensing predicate
# --------------------------------------------------------------------------

def allowed(parent_cat: str, edge: str, child_cat: str, strict: bool = False) -> bool:
    """Is the edge ``parent_cat --edge--> child_cat`` licensed by the
    conventions?

    ``strict=True`` uses the strict X-bar skeleton (the four flagged
    annotator deviations count as violations); the default uses the complete
    observed regime.
    """
    if parent_cat == ROOT:
        return edge == ROOT and child_cat in ROOT_CATS
    if edge == ROOT:
        return False
    if parent_cat not in EDGE_PARENTS.get(edge, set()):
        return False
    if child_cat not in EDGE_CHILDREN.get(edge, set()):
        return False
    if edge == "Head" and child_cat not in HEAD_ALLOWED.get(parent_cat, set()):
        return False
    xbar = XBAR_STRICT if strict else XBAR_ALLOWED
    if parent_cat in xbar and child_cat not in xbar[parent_cat]:
        return False
    return True


def licensed_children(parent_cat: str, strict: bool = False) -> "Dict[str, FrozenSet[str]]":
    """For parent category ``parent_cat``: map edge -> allowed child categories."""
    out: Dict[str, FrozenSet[str]] = {}
    for edge in EDGES:
        allowed_cats = frozenset(
            c for c in ALL_CATS if allowed(parent_cat, edge, c, strict=strict)
        )
        if allowed_cats:
            out[edge] = allowed_cats
    return out
