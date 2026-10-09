"""Evidence-based retrieval, business hypotheses, experiments, and holdings math.

Structural reuse scores measure observed source properties, never future revenue,
engineering hours saved, legal permission, or probabilistic analytical confidence.
"""
from __future__ import annotations
import math
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from brain.core import BrainError, require, timestamp, digest, same_semantic_observation

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")
TEST_SOURCE_PATH = re.compile(r"(?:^|/)(?:tests?|__tests__)(?:/|[_.])|(?:^|/)[^/]+(?:_test|\.test|\.spec)\.(?:py|ts|js|lua|rs|go)$", re.I)


def is_test_source_path(path):
    return isinstance(path, str) and TEST_SOURCE_PATH.search(path) is not None

# Separate the broad "never discover code under tests/" exclusion from
# positive evidence that an EXECUTABLE test is plausibly tied to one module.
# Filename/path association is not a claim that the tests passed or cover code.
_NON_SEMANTIC_TEST_WORDS = frozenset({
    "test", "tests", "spec", "specs", "unit", "integration", "e2e",
    "init", "index", "main", "lib", "src", "app", "apps", "script",
    "scripts", "code", "module", "mod", "mock", "mocks",
    "fixture", "fixtures", "conftest", "setup", "helper", "helpers",
    "util", "utils",
})


def _filename_tokens(path):
    basename = path.rsplit("/", 1)[-1]
    stem = basename.split(".", 1)[0]
    stem = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", stem)
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", stem)
    tokens = set()
    for word in re.findall(r"[a-z0-9]+", stem.lower()):
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s") and len(word) > 4 and not word.endswith(("ss", "us")):
            word = word[:-1]
        if len(word) > 1 and word not in _NON_SEMANTIC_TEST_WORDS and not re.fullmatch(r"v?\d+", word):
            tokens.add(word)
    return tokens


def _executable_test_path(path):
    """Fixtures/README/JSON under tests/ never confer implementation-test credit."""
    if not is_test_source_path(path):
        return False
    name = path.rsplit("/", 1)[-1]
    return bool(
        re.fullmatch(r"(?:test_[A-Za-z0-9_]+|[A-Za-z0-9_]+_test|tests(?:_[A-Za-z0-9_]+)?)\.py", name)
        or re.fullmatch(r".+\.(?:test|spec)\.(?:[jt]sx?|mjs|cjs)", name)
        or re.fullmatch(r".+_test\.go", name)
        or re.fullmatch(r"(?:test_.+|.+_test|tests)\.rs", name)
        or re.fullmatch(r".+(?:Test|Tests)\.(?:java|kt)", name)
        or re.fullmatch(r".+(?:_spec|_test)\.lua", name)
    )


def _package_scope(path):
    """Reject cross-package associations when both files identify a package."""
    parts = path.split("/")
    for index, name in enumerate(parts[:-1]):
        if name in {"apps", "packages", "services"} and index + 1 < len(parts) - 1:
            return name, parts[index + 1]
    return None


def related_test_paths(source_path, rows):
    """Return up to 10 executable tests with source-module NAME evidence.

    Shared generic directories, unrelated monorepo packages and data-only
    fixtures are insufficient. These are candidates for REVIEW, not verified
    coverage, successful executions, legal permission, or upgrade authority.
    """
    if not isinstance(source_path, str) or is_test_source_path(source_path):
        return []
    source_tokens = _filename_tokens(source_path)
    if not source_tokens:
        return []
    source_scope = _package_scope(source_path)
    related = []
    for entry in rows:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path")
        if not _executable_test_path(path):
            continue
        test_scope = _package_scope(path)
        if source_scope and test_scope and source_scope != test_scope:
            continue
        if source_tokens.isdisjoint(_filename_tokens(path)):
            continue
        related.append(path)
        if len(related) == 10:
            break
    return related

def number(value, name, minimum=Decimal('0')):
    require(type(value) in {str, int, float}, name+" must be numeric")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise BrainError(name+" invalid") from exc
    require(result.is_finite() and result >= minimum, name+" nonfinite/out of bounds")
    return result

def fields(payload, expected):
    require(set(payload) == set(expected), "payload fields invalid")

def text(value, maximum=2000):
    require(type(value) is str and 0 < len(value) <= maximum, "text missing/too long")

def validate_payload(kind, p, observed_at):
    if kind in {"repository", "candidate"}:
        require(REPO.fullmatch(p.get("repository", "")) is not None and SHA.fullmatch(p.get("head_sha", "")) is not None, "repository/exact revision invalid")
        ref = f'https://github.com/{p["repository"]}/'
        require(type(p.get("source_ref")) is str and p["source_ref"].startswith(ref), "source reference must belong to repository")
    if kind == "repository":
        fields(p, {"repository","head_sha","default_branch","checks","open_issues","source_ref"})
        text(p["default_branch"], 100)
        require(type(p["open_issues"]) is int and p["open_issues"] >= 0, "issue count invalid")
        require(type(p["checks"]) is list and len(p["checks"]) <= 500, "checks invalid")
        for check in p["checks"]:
            fields(check, {"name","status","conclusion","head_sha","url"})
            text(check["name"], 200)
            require(check["head_sha"] == p["head_sha"], "check is not bound to current source revision")
            require(check["status"] in {"queued","in_progress","completed"}, "check status invalid")
            require(check["conclusion"] in {None,"success","failure","neutral","cancelled","skipped","timed_out","action_required","stale","startup_failure"}, "check conclusion invalid")
            require(check["status"] == "completed" or check["conclusion"] is None, "nonterminal check has a conclusion")
            require(type(check["url"]) is str and check["url"].startswith(ref), "check reference invalid")
    elif kind == "candidate":
        fields(p, {"repository","head_sha","path","blob_sha","code_sha256","bytes","test_paths","license","source_ref","target","query","matched_terms"})
        require(SHA.fullmatch(p["blob_sha"] or "") is not None and re.fullmatch(r"[0-9a-f]{64}", p["code_sha256"] or ""), "source content hashes invalid")
        text(p["path"],500)
        require(not p["path"].startswith("/") and ".." not in p["path"].split("/"), "unsafe source path")
        require(p["source_ref"] == f'{ref}blob/{p["head_sha"]}/{p["path"]}', "candidate reference must use inspected exact SHA")
        require(type(p["bytes"]) is int and 0 < p["bytes"] <= 100000, "source size invalid")
        require(type(p["test_paths"]) is list and len(p["test_paths"]) <= 10 and all(type(x) is str and len(x)<=500 for x in p["test_paths"]), "test paths invalid")
        text(p["license"],100)
        text(p["target"],100)
        text(p["query"],300)
        require(type(p["matched_terms"]) is list and len(p["matched_terms"])<=20 and all(type(x) is str and len(x)<=60 for x in p["matched_terms"]), "matched terms invalid")
    elif kind == "experiment":
        fields(p, {"experiment","dataset_kind","cases","baseline_operations","candidate_operations","equal_outputs","source_ref","scope","duplicate_cases","near_duplicates"})
        require(p["experiment"] == "invoice-dedup-index-v1", "unreviewed experiment execution forbidden")
        require(p["dataset_kind"] == "SIMULATED" and p["equal_outputs"] is True, "experiment correctness/data label missing")
        require(all(type(p[x]) is int and p[x] > 0 for x in ("cases","baseline_operations","candidate_operations")), "experiment counts invalid")
        require(type(p["duplicate_cases"]) is int and p["duplicate_cases"]>0 and p["near_duplicates"]==2,"experiment must exercise positives and near misses")
        require(p["candidate_operations"] <= p["baseline_operations"], "experiment does not improve defined metric")
        text(p["scope"])
        require(p["source_ref"] == "brain/experiments.py:invoice-dedup-index-v1", "experiment source invalid")
    elif kind == "feedback":
        fields(p, {"candidate_key","outcome","evidence_ref","basis","engineering_seconds_saved"})
        text(p["candidate_key"],200)
        require(p["outcome"] in {"USEFUL","NOT_USEFUL","INTEGRATED"}, "outcome invalid")
        require(p["basis"] == "OPERATOR_REPORTED", "feedback cannot self-certify independent verification")
        text(p["evidence_ref"])
        require(p["engineering_seconds_saved"] is None or number(p["engineering_seconds_saved"],"time saved") >= 0, "time savings invalid")
    elif kind == "holdings":
        fields(p, {"currency","cash","positions","quotes","authorization","historical_prices"})
        require(p["currency"] == "USD", "USD-only foundation; FX conversion unavailable")
        number(p["cash"],"cash")
        require(p["authorization"] in {"USER_AUTHORIZED","PUBLIC","SIMULATED"}, "permitted source attestation required")
        require(type(p["positions"]) is list and 0 < len(p["positions"]) <= 100, "positions missing/too many")
        symbols = set()
        for pos in p["positions"]:
            fields(pos,{"symbol","quantity","cost_basis","sector"})
            require(re.fullmatch(r"[A-Z0-9.^-]{1,20}",pos["symbol"] or "") and pos["symbol"] not in symbols, "symbol invalid/duplicate")
            symbols.add(pos["symbol"])
            require(number(pos["quantity"],"quantity") > 0, "long-only holdings; zero/short positions unsupported")
            if pos["cost_basis"] is not None:
                number(pos["cost_basis"],"total cost basis")
            text(pos["sector"],100)
        require(type(p["quotes"]) is dict and set(p["quotes"]) == symbols, "quote coverage must exactly match holdings")
        for quote in p["quotes"].values():
            fields(quote,{"price","observed_at","source_ref","data_kind"})
            require(number(quote["price"],"price") > 0, "price must be positive")
            require(timestamp(quote["observed_at"]) <= timestamp(observed_at), "quote from future")
            text(quote["source_ref"])
            require(quote["data_kind"] in {"ACTUAL","SIMULATED","ESTIMATED"}, "quote data kind invalid")
        require(type(p["historical_prices"]) is list and len(p["historical_prices"])<=1000, "history invalid/too large")
        previous = None
        for row in p["historical_prices"]:
            fields(row,{"observed_at","prices","source_ref","data_kind"})
            dt = timestamp(row["observed_at"])
            require(dt <= timestamp(observed_at) and (previous is None or dt > previous), "history not monotonic/point-in-time")
            require(set(row["prices"]) == symbols, "history requires aligned holdings coverage")
            for value in row["prices"].values():
                require(number(value,"historical price") > 0, "history price nonpositive")
            text(row["source_ref"])
            require(row["data_kind"] in {"ACTUAL","SIMULATED","ESTIMATED"}, "history label invalid")
            previous = dt

def reuse_score(p):
    # Simple transparent ranking; never grants reuse, integration, or revenue verification.
    return (3 if p["test_paths"] else 0) + min(len(p["matched_terms"]),4) + (1 if p["bytes"] <= 30000 else 0)

def holdings_report(p):
    values = {pos["symbol"]:number(pos["quantity"],"quantity")*number(p["quotes"][pos["symbol"]]["price"],"price") for pos in p["positions"]}
    cash = number(p["cash"],"cash")
    nav = cash+sum(values.values())
    exposures = defaultdict(Decimal)
    for pos in p["positions"]:
        exposures[pos["sector"]] += values[pos["symbol"]]
    cost = sum(number(pos["cost_basis"],"cost") for pos in p["positions"] if pos["cost_basis"] is not None)
    complete_cost = all(pos["cost_basis"] is not None for pos in p["positions"])
    series = [cash+sum(number(pos["quantity"],"quantity")*number(row["prices"][pos["symbol"]],"price") for pos in p["positions"]) for row in p["historical_prices"]]
    peak, drawdown = Decimal(0), Decimal(0)
    for value in series:
        peak=max(peak,value)
        drawdown=min(drawdown,(value/peak)-1)
    returns=[float(b/a-1) for a,b in zip(series,series[1:])]
    mean=sum(returns)/len(returns) if returns else None
    volatility = math.sqrt(sum((x-mean)**2 for x in returns)/(len(returns)-1)) if len(returns)>1 else None
    return {"net_asset_value_usd":str(nav),"holding_values_usd":{k:str(v) for k,v in values.items()},"weights":{k:float(v/nav) for k,v in values.items()},"cash_weight":float(cash/nav),"sector_exposure_usd":{k:str(v) for k,v in exposures.items()},"concentration_hhi":float(sum((v/nav)**2 for v in values.values())+(cash/nav)**2),"unrealized_gain_usd":str(sum(values.values())-cost) if complete_cost else None,"stress_minus_20_percent_equities_usd":str(cash+sum(values.values())*Decimal('.8')),"history":{"basis":"FIXED_CURRENT_HOLDINGS_SCENARIO_NOT_REALIZED_PERFORMANCE","points":len(series),"total_price_return":float(series[-1]/series[0]-1) if len(series)>1 else None,"max_drawdown":float(drawdown) if series else None,"sample_volatility_per_observation":volatility,"annualized_volatility":None},"execution_authority":False}

def build_report(events, *, now, max_age):
    latest = {}
    observed_facts = {}
    for event in events:
        # Inspect ALL semantic times, not only the latest key-level sample:
        # a newer observation must never conceal older conflicting labels.
        identity = (event["kind"], event["key"], event["observed_at"])
        prior = observed_facts.get(identity)
        if prior is None:
            observed_facts[identity] = event
        else:
            require(
                same_semantic_observation(prior, event),
                "AMBIGUOUS_OBSERVATION: conflicting equal-time payload or classification",
            )
        key=(event["kind"],event["key"])
        old=latest.get(key)
        if old is None or (timestamp(event["observed_at"]),event["id"]) > (timestamp(old["observed_at"]),old["id"]):
            latest[key]=event
    current=list(latest.values())
    semantic=[e["observed_at"] for e in current if e["kind"] in {"repository","holdings"}]
    require(all(timestamp(e["observed_at"])<=timestamp(now) for e in current), "FUTURE_SOURCE: report time precedes observation")
    semantic.extend(q["observed_at"] for e in current if e["kind"]=="holdings" for q in e["payload"]["quotes"].values())
    stale=[e["key"] for e in current if e["kind"] in {"repository","holdings"} and (timestamp(now)-timestamp(e["observed_at"])).total_seconds()>max_age]
    stale_quotes=[e["key"] for e in current if e["kind"]=="holdings" and any((timestamp(now)-timestamp(q["observed_at"])).total_seconds()>max_age for q in e["payload"]["quotes"].values())]
    repos=[{"key":e["key"],"observed_at":e["observed_at"],"data_kind":e["data_kind"],**e["payload"]} for e in current if e["kind"]=="repository"]
    # Reconcile legacy persisted candidate paths when replaying old events.
    # Old observations may include unrelated repo tests or data-only fixtures;
    # never allow stored structural mistakes to retain ranking/upgrade credit.
    candidates=[]
    for e in current:
        if e["kind"]!="candidate" or is_test_source_path(e["payload"].get("path")):
            continue
        p=dict(e["payload"])
        p["test_paths"]=related_test_paths(
            p["path"], [{"path":path,"type":"blob"} for path in p["test_paths"]]
        )
        candidates.append({"key":e["key"],"observed_at":e["observed_at"],
            "data_kind":e["data_kind"],"reuse_score":reuse_score(p),
            "utility_evidence":"STRUCTURAL_ONLY_NOT_EXECUTED",**p})
    candidates.sort(key=lambda x:(-x["reuse_score"],x["key"]))
    feedback=[e["payload"] for e in current if e["kind"]=="feedback"]
    feedback_by_key={x["candidate_key"]:x for x in feedback}
    for candidate in candidates:
        candidate["feedback"]=feedback_by_key.get(candidate["key"])
        candidate["freshness"]="CURRENT" if (timestamp(now)-timestamp(candidate["observed_at"])).total_seconds()<=max_age else "HISTORICAL"
    opportunities=[{"target":c["target"],"candidate_key":c["key"],"source_ref":c["source_ref"],"hypothesis":"Evaluate this implementation and its tests against the project's requirements before reimplementation.","next_experiment":"Run project-specific correctness and adversarial tests in an isolated environment after source review.","customer_demand":"UNVERIFIED","revenue":"UNAVAILABLE","hours_saved":"UNMEASURED"} for c in candidates[:10]]
    return {"schema_version":2,"status":"PASS" if semantic and not stale and not stale_quotes else "BLOCKED","scope":"READ_ONLY_BUSINESS_PORTFOLIO_INTELLIGENCE","evidence_basis":"OBSERVATIONS_AND_EXPLICITLY_LABELLED_EXPERIMENTS","stale_sources":sorted(set(stale+stale_quotes)),"semantic_timestamps":semantic,"repositories":repos,"reuse_candidates":candidates,"business_opportunities":opportunities,"learning":{"facts":len(current),"events":len(events),"outcomes":feedback,"experiments":[e["payload"] for e in current if e["kind"]=="experiment"],"autonomous_code_execution":False,"verified_revenue":None,"prediction_confidence":None},"holdings":[{"key":e["key"],"data_kind":e["data_kind"],"quote_data_kinds":sorted(set(q["data_kind"] for q in e["payload"]["quotes"].values())),"sources":[q["source_ref"] for q in e["payload"]["quotes"].values()],**holdings_report(e["payload"])} for e in current if e["kind"]=="holdings"]}
