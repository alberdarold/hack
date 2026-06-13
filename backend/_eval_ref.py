"""Run the 12 reference questions through the agent and time each one."""
import time
from dotenv import load_dotenv

load_dotenv()
import agent

QUESTIONS = [
    ("01 CRM aggregate", "How many open opportunities does Primato Supermercati S.p.A. (CUST-0132) have, and what is their total value?"),
    ("02 ERP single", "Is SKU PAS-PEN-500 (Penne Rigate n.73 - 500g) below its minimum stock? Give the on-hand quantity."),
    ("03 Calls single", "In the last call with NordSpesa S.p.A. (CUST-0137), what was the complaint and which lot did it concern?"),
    ("04 KB single", "What is the shelf life (TMC) and the declared allergens for Spaghetti n.5 - 500g (SKU PAS-SPA-500)?"),
    ("05 Calls multi", "Does the complaint from that last NordSpesa call qualify for a return under the quality policy?"),
    ("06 CRM aggregate", "Total value of opportunities in the negotiation stage, grouped by customer channel (GDO / distributor / horeca)."),
    ("07 ERP trap", "What is the profit margin on lot LOT-2026-0658?"),
    ("08 CRM trap", "What is the status of the order for Supermercati Bianchi?"),
    ("09 CRM generation", "Generate a 4-slide HTML deck for the sales rep visiting Primato Supermercati S.p.A.: profile, open deals, order/lot status, recent call complaints."),
    ("10 ERP multi", "Which semolina does SKU PAS-SPA-500 use (per its bill of materials), which supplier provides it, and is that raw material below minimum stock?"),
    ("11 Calls aggregate", "Across ALL recorded calls (there are 80 - you must page through the entire call log, do not stop at the first page), count how many quality complaints concern the defect 'broken pasta'. Give the exact number."),
    ("12 KB multi", "GranMercato S.p.A. (also written 'Gran Mercato S.p.A.' in some notes) asked about the price of Fusilli n.98 - 500g box (PAS-FUS-500). A call mentions one figure and the official 2026 wholesale price list mentions another. Which is the correct list price, and why?"),
]

for label, q in QUESTIONS:
    t0 = time.time()
    try:
        res = agent.answer_question(q)
        dt = time.time() - t0
        print("=" * 80)
        print(f"[{label}]  ({dt:.1f}s)")
        print("Q:", q)
        print("A:", res.answer[:600])
        print("sources:", res.sources, "| verticale:", res.verticale, "| artifact:", res.artifact_url)
    except Exception as exc:
        print("=" * 80)
        print(f"[{label}]  HANDLER ERROR:", type(exc).__name__, exc)
print("=" * 80)
print("DONE")
