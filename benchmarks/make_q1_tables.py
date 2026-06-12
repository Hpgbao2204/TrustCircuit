"""Render the Q1 result CSVs into LaTeX tables (booktabs) for the paper.

Every table is written as a self-contained fragment under results/q1/tables/
and can be pulled into the paper with \\input{...}. Tables are the deliverable
for results that are not plotted as figures.

Marker mapping for capability cells:
    yes -> \\ding{51}   partial -> $\\sim$   no -> ---   n/r -> n/r
"""

from __future__ import annotations

import csv
from pathlib import Path

SUM = Path("results/q1/summary")
LEGACY = Path("results/summary")
TAB = Path("results/q1/tables")

MARK = {"yes": r"\ding{51}", "partial": r"$\sim$", "no": r"---", "n/r": r"n/r"}


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def esc(s: str) -> str:
    return (s.replace("&", r"\&").replace("%", r"\%").replace("_", r"\_"))


def write(name: str, body: str) -> Path:
    TAB.mkdir(parents=True, exist_ok=True)
    out = TAB / name
    out.write_text(body, encoding="utf-8")
    return out


def num(x: str, fmt: str = "{:,.0f}") -> str:
    try:
        return fmt.format(float(x)).replace(",", "{,}")
    except (ValueError, TypeError):
        return esc(str(x))


# ---------------------------------------------------------------------------
# Table A: modern capability matrix (the main replacement table).
# ---------------------------------------------------------------------------
def table_capability() -> Path:
    rows = read(SUM / "modern_sota_capability.csv")
    dims = ["verifiable_dp", "zk_compliance", "blockchain_settlement", "budget_accounting",
            "proof_binding", "replay_nullifier", "audit_support", "confidential_compute"]
    head = ["VDP", "ZK comp.", "BC settle", "Budget", "Bind", "Replay", "Audit", "Conf."]
    lines = [
        r"\begin{table*}[!t]", r"\centering",
        r"\caption{Capability comparison against modern (2022--2026) verifiable-DP, ZK-compliance, "
        r"verifiable-FL, and confidential-compute systems. \ding{51}~direct, $\sim$~partial/indirect, "
        r"---~out of scope. Qualitative by design (no subjective score).}",
        r"\label{tab:modern_capability}", r"\footnotesize", r"\setlength{\tabcolsep}{3pt}",
        r"\renewcommand{\arraystretch}{1.12}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{@{}llcccccccll@{}}", r"\toprule",
        r"\textbf{System} & \textbf{Yr} & " + " & ".join(f"\\textbf{{{h}}}" for h in head)
        + r" & \textbf{Main limitation} \\", r"\midrule",
    ]
    for r in rows:
        is_tc = r["system"] == "TrustCircuit"
        name = (r"\textbf{%s}" % esc(r["system"])) if is_tc else esc(r["system"])
        cells = " & ".join(MARK[r[d]] for d in dims)
        limit = esc(r["main_limitation"])
        line = f"{name} & {r['year']} & {cells} & {limit} \\\\"
        lines.append(line)
        if is_tc:
            lines.insert(len(lines) - 1, r"\midrule")
    lines += [r"\bottomrule", r"\end{tabular}}", r"\end{table*}", ""]
    return write("tableA_modern_capability.tex", "\n".join(lines))


# ---------------------------------------------------------------------------
# Table 3: quantitative ZK/VDP overhead (measured TC + literature baselines).
# ---------------------------------------------------------------------------
def table_overhead() -> Path:
    rows = read(SUM / "modern_sota_comparison.csv")
    lines = [
        r"\begin{table*}[!t]", r"\centering",
        r"\caption{Quantitative comparison with recent verifiable-privacy and ZK-compliance systems. "
        r"TrustCircuit rows are \emph{measured} in this work on the same compliance circuit; external "
        r"rows are the cited paper's own reported figures (n/r: not reported). \emph{Lifecycle binding} "
        r"counts the request-context fields the proof is cryptographically bound to (request, asset, "
        r"consumer, policy, $\varepsilon$, nullifier, audit)---the dimension where TrustCircuit is unique.}",
        r"\label{tab:modern_overhead}", r"\scriptsize", r"\setlength{\tabcolsep}{3pt}",
        r"\renewcommand{\arraystretch}{1.15}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{@{}llllcllrrrl@{}}", r"\toprule",
        r"\textbf{System} & \textbf{Yr} & \textbf{Target problem} & \textbf{Proof type} & "
        r"\textbf{On-chain} & \textbf{Proof sys.} & \textbf{Prove} & \textbf{Verify} & "
        r"\textbf{Proof} & \textbf{Gas} & \textbf{Lifecycle binding} \\",
        r" &  &  &  & \textbf{verify} &  & \textbf{(ms)} & \textbf{(ms)} & \textbf{(B)} & "
        r"\textbf{(on-chain)} &  \\", r"\midrule",
    ]

    def cell(v: str, fmt: str = "{:,.1f}") -> str:
        if v in ("n/r", ""):
            return "n/r"
        try:
            return fmt.format(float(v)).replace(",", "{,}")
        except ValueError:
            return esc(v)

    tc_done = False
    for r in rows:
        is_tc = r["system"].startswith("TrustCircuit")
        if not is_tc and not tc_done:
            lines.append(r"\midrule")
            tc_done = True
        name = (r"\textbf{%s}" % esc(r["system"])) if is_tc else esc(r["system"])
        onchain = MARK.get(r["onchain_verify"], r["onchain_verify"])
        prove = cell(r["prove_time_ms"], "{:,.0f}")
        verify = cell(r["verify_time_ms"], "{:.2f}")
        size = cell(r["proof_size_bytes"], "{:,.0f}")
        gas = cell(r["onchain_gas"], "{:,.0f}")
        binding = esc(r["lifecycle_binding"])
        if r["lifecycle_binding"].startswith("full"):
            binding = r"\textbf{%s}" % binding
        lines.append(
            f"{name} & {r['year']} & {esc(r['target_problem'])} & {esc(r['proof_type'])} & "
            f"{onchain} & {esc(r['proof_system'])} & {prove} & {verify} & {size} & {gas} & {binding} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}}", r"\end{table*}", ""]
    return write("table3_modern_overhead.tex", "\n".join(lines))


# ---------------------------------------------------------------------------
# Table B: measured E2E ablation.
# ---------------------------------------------------------------------------
E2E_ORDER = ["OffChain", "ACL-Only", "NoBudget", "NoZK", "TC-Full-MockZK",
             "TC-Full-ZK-VerifyOnly", "TC-Full-ZK-ProveAndVerify"]
E2E_GUARANTEE = {
    "OffChain": "none (local only)", "ACL-Only": "+access control",
    "NoBudget": "+confidential compute", "NoZK": "+privacy budget",
    "TC-Full-MockZK": "+proof record (mock)", "TC-Full-ZK-VerifyOnly": "+on-chain ZK verify",
    "TC-Full-ZK-ProveAndVerify": "+real ZK proving",
}


def table_e2e() -> Path:
    rows = {r["variant"]: r for r in read(SUM / "e2e_ablation_summary.csv")}
    lines = [
        r"\begin{table*}[!t]", r"\centering",
        r"\caption{Measured end-to-end ablation over 50 runs per variant on the local EVM with real "
        r"contracts and a real Groth16 proof. Each variant adds one guarantee. Latencies are wall-clock; "
        r"gas is per full request.}",
        r"\label{tab:e2e_ablation}", r"\footnotesize", r"\setlength{\tabcolsep}{4pt}",
        r"\renewcommand{\arraystretch}{1.1}",
        r"\begin{tabular}{@{}llrrrrrr@{}}", r"\toprule",
        r"\textbf{Variant} & \textbf{Added guarantee} & \textbf{Mean (ms)} & \textbf{p95 (ms)} & "
        r"\textbf{p99 (ms)} & \textbf{Total gas} & \textbf{Proof gas} & \textbf{req/s} \\", r"\midrule",
    ]
    for v in E2E_ORDER:
        if v not in rows:
            continue
        r = rows[v]
        name = esc(v)
        if v.startswith("TC-Full-ZK-ProveAndVerify"):
            name = r"\textbf{%s}" % name
        lines.append(
            f"{name} & {E2E_GUARANTEE[v]} & {num(r['mean_latency_ms'], '{:.1f}')} & "
            f"{num(r['p95_latency_ms'], '{:.1f}')} & {num(r['p99_latency_ms'], '{:.1f}')} & "
            f"{num(r['total_gas'])} & {num(r['proof_gas'])} & {num(r['throughput_req_s'], '{:.1f}')} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
    return write("tableB_e2e_ablation.tex", "\n".join(lines))


# ---------------------------------------------------------------------------
# Table C: ZK scheme comparison (from existing measured selection matrix).
# ---------------------------------------------------------------------------
def table_zk() -> Path:
    rows = read(LEGACY / "zk_scheme_selection.csv")
    lines = [
        r"\begin{table}[!t]", r"\centering",
        r"\caption{Proof-system comparison on the same compliance circuit. Groth16/PLONK/fflonk are "
        r"measured in this work; STARK/Bulletproofs are literature-characterised (measured=0).}",
        r"\label{tab:zk_scheme}", r"\footnotesize", r"\setlength{\tabcolsep}{3.5pt}",
        r"\renewcommand{\arraystretch}{1.1}",
        r"\begin{tabular}{@{}llrrrl@{}}", r"\toprule",
        r"\textbf{Scheme} & \textbf{Setup} & \textbf{Proof (B)} & \textbf{Prove (ms)} & "
        r"\textbf{Verify gas} & \textbf{Best use} \\", r"\midrule",
    ]
    rec_short = {
        "groth16": "smallest proof, cheap verify",
        "plonk": "universal setup, editable rules",
        "fflonk": "lowest verify gas, heavy prover",
        "stark": "transparent+PQ, L2 verify",
        "bulletproofs": "no setup, costly verify",
    }
    for r in rows:
        meas = "" if r["measured"] == "1" else r"$^{\dagger}$"
        name = esc(r["scheme"]) + meas
        lines.append(
            f"{name} & {esc(r['setup_model'])} & {num(r['proof_size_bytes'])} & "
            f"{num(r['prove_time_ms'], '{:.1f}')} & {num(r['verify_onchain_gas'])} & "
            f"{rec_short.get(r['scheme'], '')} \\\\")
    lines += [r"\bottomrule",
              r"\multicolumn{6}{@{}l@{}}{\scriptsize $^{\dagger}$literature-characterised, not measured here.}\\",
              r"\end{tabular}", r"\end{table}", ""]
    return write("tableC_zk_scheme.tex", "\n".join(lines))


# ---------------------------------------------------------------------------
# Table D: concurrent budget double-spend.
# ---------------------------------------------------------------------------
def table_double_spend() -> Path:
    rows = read(SUM / "budget_double_spend_by_concurrency.csv")
    lines = [
        r"\begin{table}[!t]", r"\centering",
        r"\caption{Concurrent double-spend stress test: up to $K$ reservations submitted into the same "
        r"block against a fixed budget (averaged over $\varepsilon\in\{0.25,0.5,1.0\}$, "
        r"budget$\in\{2,5,10\}$, 50 trials each). The ledger never overspends.}",
        r"\label{tab:double_spend}", r"\footnotesize", r"\setlength{\tabcolsep}{5pt}",
        r"\renewcommand{\arraystretch}{1.1}",
        r"\begin{tabular}{@{}rrrrr@{}}", r"\toprule",
        r"\textbf{Concurrency} & \textbf{Blocked} & \textbf{Overspend acc.} & "
        r"\textbf{Attack succ.} & \textbf{Budget consistent} \\", r"\midrule",
    ]
    for r in rows:
        lines.append(
            f"{r['concurrency']} & {num(r['blocked_rate'], '{:.3f}')} & "
            f"{num(r['overspend_accepted_rate'], '{:.3f}')} & {num(r['attack_success_rate'], '{:.3f}')} & "
            f"{num(r['final_budget_consistent_rate'], '{:.3f}')} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return write("tableD_double_spend.tex", "\n".join(lines))


# ---------------------------------------------------------------------------
# Budget composition table.
# ---------------------------------------------------------------------------
def table_budget_composition() -> Path:
    rows = read(SUM / "budget_composition_summary.csv")
    # show epsilon=0.25 slice (representative) for compactness.
    sel = [r for r in rows if abs(float(r["epsilon"]) - 0.25) < 1e-9]
    order = ["NoBudget", "TrustedOffChainBudget", "ConsumeOnlyLedger",
             "TrustCircuitReserveConsume", "TrustCircuitReserveConsumeZK"]
    by = {r["regime"]: r for r in sel}
    lines = [
        r"\begin{table}[!t]", r"\centering",
        r"\caption{Privacy-budget composition over 100 requests at $\varepsilon=0.25$ against a budget "
        r"of $5.0$. Only the unaccounted regime overspends; all ledger regimes conserve the budget.}",
        r"\label{tab:budget_composition}", r"\footnotesize", r"\setlength{\tabcolsep}{4pt}",
        r"\renewcommand{\arraystretch}{1.1}",
        r"\begin{tabular}{@{}lrrrrr@{}}", r"\toprule",
        r"\textbf{Regime} & \textbf{Acc.} & \textbf{Rej.} & \textbf{Remain.} & "
        r"\textbf{Overspend} & \textbf{Violations} \\", r"\midrule",
    ]
    for rg in order:
        if rg not in by:
            continue
        r = by[rg]
        name = esc(rg.replace("TrustCircuit", "TC-"))
        lines.append(
            f"{name} & {r['accepted_requests']} & {r['rejected_requests']} & "
            f"{num(r['remaining_budget'], '{:.2f}')} & {num(r['overspend_amount'], '{:.2f}')} & "
            f"{r['budget_invariant_violations']} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return write("tableE_budget_composition.tex", "\n".join(lines))


# ---------------------------------------------------------------------------
# Proof-binding attack table.
# ---------------------------------------------------------------------------
def table_binding() -> Path:
    rows = read(SUM / "proof_binding_attacks_summary.csv")
    acc = {"1": r"\ding{51}", "0": r"---"}
    lines = [
        r"\begin{table}[!t]", r"\centering",
        r"\caption{Proof-binding attacks. A cryptographically valid proof is replayed/misbound under "
        r"seven cases. \ding{51}~accepted, ---~rejected. Only the request-bound adapter rejects every "
        r"misuse while accepting the honest case.}",
        r"\label{tab:proof_binding}", r"\footnotesize", r"\setlength{\tabcolsep}{5pt}",
        r"\renewcommand{\arraystretch}{1.1}",
        r"\begin{tabular}{@{}lcccl@{}}", r"\toprule",
        r"\textbf{Case} & \textbf{Mock} & \textbf{Raw G16} & \textbf{Adapter} & \textbf{Adapter revert} \\",
        r"\midrule",
    ]
    for r in rows:
        case = esc(r["attack_case"])
        revert = esc(r["adapter_revert"]) if r["adapter_revert"] else "---"
        lines.append(
            f"{case} & {acc[str(r['accepted_by_mock'])]} & {acc[str(r['accepted_by_raw_verifier'])]} & "
            f"{acc[str(r['accepted_by_adapter'])]} & {revert} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return write("tableF_proof_binding.tex", "\n".join(lines))


# ---------------------------------------------------------------------------
# TEE redundancy summary table (worst-case rows).
# ---------------------------------------------------------------------------
def table_tee() -> Path:
    rows = read(SUM / "tee_redundancy_attacks_summary.csv")
    fracs = [0.1, 0.25, 0.33, 0.5]
    configs = ["single_worker", "3_worker_majority", "5_worker_majority", "7_worker_majority"]
    by = {(r["config"], float(r["malicious_fraction"])): r for r in rows}
    lines = [
        r"\begin{table}[!t]", r"\centering",
        r"\caption{Simulator-level TEE robustness (100 trials, averaged over attack types). Majority "
        r"redundancy drives the attack-success rate to zero until malicious workers form a majority. "
        r"This evaluates protocol robustness, not SGX hardware security.}",
        r"\label{tab:tee_redundancy}", r"\footnotesize", r"\setlength{\tabcolsep}{4pt}",
        r"\renewcommand{\arraystretch}{1.1}",
        r"\begin{tabular}{@{}lrrrr@{}}", r"\toprule",
        r"\textbf{Config} & " + " & ".join(f"\\textbf{{m={f}}}" for f in fracs) + r" \\",
        r"\multicolumn{5}{@{}l@{}}{\scriptsize attack-success rate at malicious fraction $m$} \\",
        r"\midrule",
    ]
    for c in configs:
        cells = " & ".join(num(by[(c, f)]["mean_attack_success_rate"], "{:.2f}") for f in fracs)
        lines.append(f"{esc(c.replace('_', ' '))} & {cells} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return write("tableG_tee_redundancy.tex", "\n".join(lines))


# ---------------------------------------------------------------------------
# Public-dataset DP utility table.
# ---------------------------------------------------------------------------
def table_public_dp() -> Path:
    rows = read(SUM / "public_dp_utility_summary.csv")
    source = rows[0]["dataset_source"] if rows else "uci"
    queries = sorted({r["query"] for r in rows})
    eps = sorted({float(r["epsilon"]) for r in rows})
    by = {(r["query"], float(r["epsilon"])): r for r in rows}
    lines = [
        r"\begin{table}[!t]", r"\centering",
        r"\caption{Differential-privacy utility on the public UCI Adult dataset (source: "
        f"{esc(source)}). Mean relative error (\\%) over 500 trials per cell under the Gaussian "
        r"mechanism; error falls smoothly as $\varepsilon$ grows.}",
        r"\label{tab:public_dp}", r"\footnotesize", r"\setlength{\tabcolsep}{4pt}",
        r"\renewcommand{\arraystretch}{1.1}",
        r"\begin{tabular}{@{}l" + "r" * len(eps) + r"@{}}", r"\toprule",
        r"\textbf{Query} & " + " & ".join(f"$\\varepsilon$={e}" for e in eps) + r" \\", r"\midrule",
    ]
    for q in queries:
        cells = " & ".join(num(by[(q, e)]["relative_error_percent_mean"], "{:.3f}") for e in eps)
        lines.append(f"{esc(q)} & {cells} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    return write("tableH_public_dp.tex", "\n".join(lines))


def main() -> None:
    outs = [
        table_capability(), table_overhead(), table_e2e(), table_zk(),
        table_double_spend(), table_budget_composition(), table_binding(),
        table_tee(), table_public_dp(),
    ]
    for o in outs:
        print(o)


if __name__ == "__main__":
    main()
