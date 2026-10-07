"""Reviewed, bounded experiment code. Discovered source is never executed."""
from brain.core import require

def invoice_dedup_experiment(count=500):
    require(type(count) is int and 20 <= count <= 2000, "experiment size must be 20..2000")
    # Deliberately labelled generated input; no customer invoices or savings claim.
    base=[(f'CARRIER-{i%7}',f'INV-{i}',i%23) for i in range(min(count//2,113))]
    rows=[base[i%len(base)] for i in range(count-2)]
    rows.extend([(base[0][0]+'-OTHER',base[0][1],base[0][2]),(base[0][0],base[0][1],base[0][2]+100)])
    baseline, operations=[] ,0
    for index,row in enumerate(rows):
        duplicate=False
        for earlier in rows[:index]:
            operations+=1
            if row==earlier:
                duplicate=True
                break
        if duplicate:
            baseline.append(index)
    seen=set()
    candidate=[]
    for index,row in enumerate(rows):
        if row in seen:
            candidate.append(index)
        seen.add(row)
    require(baseline==candidate, "candidate failed correctness oracle")
    return {"experiment":"invoice-dedup-index-v1","dataset_kind":"SIMULATED","cases":count,"baseline_operations":operations,"candidate_operations":count,"equal_outputs":True,"duplicate_cases":len(candidate),"near_duplicates":2,"source_ref":"brain/experiments.py:invoice-dedup-index-v1","scope":"Exact tuple duplicate detection; operation counts only; does not prove freight overpayment, production speed, revenue, or engineering time savings."}
