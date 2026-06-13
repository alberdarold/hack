from dotenv import load_dotenv
load_dotenv()
from api_client import AlDenteApiClient

api = AlDenteApiClient()
calls = api.calls()
print("total calls:", len(calls))

topic_bp = [c for c in calls if "broken pasta" in str(c.get("topic", "")).lower()]
summary_bp = [c for c in calls if "broken pasta" in str(c.get("summary", "")).lower()]
topic_or_summary = [c for c in calls if "broken pasta" in (str(c.get("topic","")) + " " + str(c.get("summary",""))).lower()]
broken_any = [c for c in calls if "broken" in (str(c.get("topic","")) + " " + str(c.get("summary",""))).lower()]
complaint_bp = [c for c in topic_or_summary if c.get("outcome") in ("complaint_open", "resolved", "follow_up")]

print("topic has 'broken pasta':", len(topic_bp))
print("summary has 'broken pasta':", len(summary_bp))
print("topic OR summary 'broken pasta':", len(topic_or_summary))
print("any 'broken':", len(broken_any))
print("topic/summary bp AND complaint outcome:", len(complaint_bp))

# Show outcomes distribution for broken-pasta calls
from collections import Counter
print("outcomes for bp calls:", Counter(c.get("outcome") for c in topic_or_summary))
print("types for bp calls:", Counter(c.get("type") for c in topic_or_summary))

# Print the topic/summary of broken-related calls to eyeball
for c in broken_any:
    print(c.get("id"), "|", c.get("outcome"), "|", c.get("topic"), "|", str(c.get("summary"))[:80])
print("DONE")
