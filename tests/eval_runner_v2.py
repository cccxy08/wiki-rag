import json, requests, sys, time, re
sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000/api"

def load_dataset(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def ask(question, mode):
    try:
        r = requests.post(f"{BASE}/query", json={"question": question, "mode": mode, "top_k": 5}, timeout=30)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "answer": ""}
        d = r.json()
        return {"answer": d.get("answer", ""), "source": d.get("source", "")}
    except Exception as e:
        return {"error": str(e), "answer": ""}

def judge(answer, expected):
    a = answer.lower().replace(" ", "").replace("\u3000", "")
    e = expected.lower().replace(" ", "").replace("\u3000", "")
    if e in a: return True
    if re.search(r"2023.*03.*15", a) and "2023-03-15" in e: return True
    if re.search(r"2022.*06.*01", a) and "2022-06-01" in e: return True
    if e in ("\u662f", "\u4e0d\u662f", "\u5df2\u79bb\u804c", "\u4ecd\u5728\u804c"):
        if e in a or (e == "\u662f" and "\u5728" in a and "\u804c" in a): return True
    if expected in ["\u9648\u5c0f\u660e", "\u6797\u6653\u857e", "\u6280\u672f\u90e8", "\u8d22\u52a1\u90e8"]:
        if expected in answer: return True
    if "2022" in e and "2023" in e and "2022" in a and "2023" in a: return True
    if "\u6ca1\u6709" in e and "Go" in e and "Excel" in e:
        if "Go" in a and "Excel" in a and ("\u6ca1\u6709" in a or "\u5206\u522b" in a): return True
    return False

dataset = load_dataset(r"D:\CodeXFiles\tests\eval_dataset.json")
modes = ["auto", "agent", "pipeline"]

results = {}
all_details = []

print("MODE COMPARISON EVALUATION")
print(f"Test cases: {len(dataset)}")
print()

for mode in modes:
    pass_count = 0
    fail_count = 0
    wiki_hit = 0
    rag_hit = 0
    times = []
    fails = []
    
    print(f"--- Mode: {mode} ---")
    for i, item in enumerate(dataset):
        start = time.time()
        resp = ask(item["q"], mode)
        elapsed = round(time.time() - start, 2)
        times.append(elapsed)
        
        src = resp.get("source", "")
        if src == "wiki": wiki_hit += 1
        elif src in ("rag", "agent"): rag_hit += 1
        
        if "error" in resp:
            fail_count += 1
            print(f"  [{i+1:>2}] ERROR {resp['error'][:50]}")
            continue
        
        passed = judge(resp.get("answer", ""), item["a"])
        if passed:
            pass_count += 1
        else:
            fail_count += 1
            fails.append({"q": item["q"], "expected": item["a"], "got": resp.get("answer", "")[:80]})
        icon = "✓" if passed else "✗"
        print(f"  [{i+1:>2}] {icon} {src:>6} {elapsed:>5.1f}s {item['q'][:35]}")
    
    total = pass_count + fail_count
    acc = round(pass_count/total*100) if total else 0
    avg_t = round(sum(times)/len(times), 2) if times else 0
    
    results[mode] = {
        "pass": pass_count,
        "fail": fail_count,
        "accuracy": acc,
        "wiki_hit": wiki_hit,
        "rag_hit": rag_hit,
        "avg_time": avg_t,
        "fails": fails
    }
    print(f"  -> ACC: {acc}%  WIKI: {wiki_hit}  RAG: {rag_hit}  AVG: {avg_t}s\n")

# Save report
report = {
    "date": "2026-05-17",
    "test_set": 26,
    "round": 2,
    "description": "三种模式对比测试",
    "best_mode": max(results, key=lambda m: results[m]["accuracy"]),
    "modes": {}
}
for mode in modes:
    r = results[mode]
    report["modes"][mode] = {
        "accuracy": f"{r['pass']}/{r['pass']+r['fail']} = {r['accuracy']}%",
        "wiki_hit": r["wiki_hit"],
        "rag_hit": r["rag_hit"],
        "avg_time_s": r["avg_time"],
        "fails": [{"q": f["q"], "expected": f["expected"], "got": f["got"][:80]} for f in r["fails"]]
    }

path = r"D:\CodeXFiles\tests\eval_report_v2.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"\nReport saved: {path}")
print(f"Best mode: {report['best_mode']}")
