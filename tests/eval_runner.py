import json, requests, sys, time
sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000/api"

def load_dataset(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def ask(question, mode="auto"):
    try:
        r = requests.post(f"{BASE}/query", json={"question": question, "mode": mode, "top_k": 5}, timeout=30)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "answer": "", "source": ""}
        data = r.json()
        return {"answer": data.get("answer", ""), "source": data.get("source", "")}
    except Exception as e:
        return {"error": str(e), "answer": "", "source": ""}

def judge(answer: str, expected: str) -> bool:
    a = answer.lower()
    e = expected.lower()
    return e in a or a[:len(e)] == e

results = {"total": 0, "wiki_hit": 0, "pass": 0, "fail": 0, "errors": 0, "times": []}
fails = []

dataset = load_dataset(r"D:\CodeXFiles\tests\eval_dataset.json")

print(f"Starting evaluation on {len(dataset)} test cases...\n")

for i, item in enumerate(dataset):
    start = time.time()
    resp = ask(item["q"], "auto")
    elapsed = round(time.time() - start, 2)
    results["times"].append(elapsed)
    results["total"] += 1
    
    if resp.get("source") == "wiki":
        results["wiki_hit"] += 1
    
    if "error" in resp and resp.get("error"):
        results["errors"] += 1
        print(f"[{i+1:>2}] {item["q"][:30]:<30} ERROR {resp["error"]}")
        continue
    
    if judge(resp.get("answer", ""), item["a"]):
        results["pass"] += 1
        icon = "✓" if resp.get("source") == "wiki" else "R"
        print(f"[{i+1:>2}] {item["q"][:30]:<30} {icon} {elapsed:>5.1f}s")
    else:
        results["fail"] += 1
        print(f"[{i+1:>2}] {item["q"][:30]:<30} ✗ {elapsed:>5.1f}s")
        fails.append({"q": item["q"], "expected": item["a"], "got": resp.get("answer", "")[:100]})

# Report
total = results["total"]
passed = results["pass"]
wiki_hit = results["wiki_hit"]
errors = results["errors"]
failed = results["fail"]
avg_time = round(sum(results["times"]) / max(len(results["times"]), 1), 2)

print(f"\n{'='*50}")
print(f"EVALUATION REPORT")
print(f"{'='*50}")
print(f"Date: 2026-05-17")
print(f"Test set: {total} cases")
print(f"")
print(f"Accuracy:        {passed}/{total} = {round(passed/total*100)}%")
print(f"Wiki hit rate:   {wiki_hit}/{total} = {round(wiki_hit/total*100)}%")
print(f"RAG recall:      {total-wiki_hit-errors-failed}/{total-wiki_hit-errors} = {round((total-wiki_hit-errors-failed)/max(total-wiki_hit-errors,1)*100)}%")
print(f"Errors:          {errors}")
print(f"Avg response:    {avg_time}s")
print(f"")
print(f"TO IMPROVE:")
for f in fails:
    print(f"  - Q: {f['q']}")
    print(f"    Expected: {f['expected'][:60]}")
    print(f"    Got: {f['got'][:80]}")
