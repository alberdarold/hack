"""Temporary smoke test of agent handlers against the live API."""
import time
from dotenv import load_dotenv
load_dotenv()
import agent

questions = [
    "How many open opportunities does Primato Supermercati S.p.A. (CUST-0132) have, and what is their total value?",
    "Total value of opportunities in the negotiation stage, grouped by customer channel (GDO / distributor / horeca).",
    "Is SKU PAS-PEN-500 below its minimum stock? Give the on-hand quantity.",
    "Which semolina does SKU PAS-SPA-500 use per its bill of materials, which supplier provides it, and is that raw material below minimum stock?",
    "In the last call with NordSpesa S.p.A. (CUST-0137), what was the complaint and which lot did it concern?",
    "Does the complaint from that last NordSpesa S.p.A. (CUST-0137) call qualify for a return under the quality policy?",
    "What is the shelf life (TMC) and the declared allergens for Spaghetti n.5 - 500g box (SKU PAS-SPA-500)?",
    "What is the status of the order for Supermercati Bianchi?",
    "What is the profit margin on lot LOT-2026-0658?",
    "Which is the correct list price of Fusilli n.98 (PAS-FUS-500)?",
]
for q in questions:
    t0 = time.time()
    try:
        res = agent.answer_question(q)
        dt = time.time() - t0
        print("=" * 70)
        print(f"Q ({dt:.1f}s):", q[:80])
        print("A:", res.answer[:320])
        print("sources:", res.sources, "| verticale:", res.verticale, "| artifact:", res.artifact_url)
    except Exception as exc:
        print("HANDLER ERROR:", type(exc).__name__, exc)

# Broken-pasta aggregate (makes ~80 transcript calls; time it).
t0 = time.time()
try:
    q = "Across ALL recorded calls count how many quality complaints concern the defect 'broken pasta'. Give the exact number."
    res = agent.answer_question(q)
    print("=" * 70)
    print(f"Q ({time.time()-t0:.1f}s):", q[:80])
    print("A:", res.answer[:200], "| sources:", res.sources)
except Exception as exc:
    print("HANDLER ERROR:", type(exc).__name__, exc)
print("DONE")
