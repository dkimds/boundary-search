import subprocess, re, json, datetime, collections, argparse

FIXPAT = re.compile(r'\b(fix|hotfix|regression|bug|revert|closes #\d+)\b', re.I)
SRC = re.compile(r'^src/.*\.(ts|tsx)$')

def load_commits(repo, branch, since):
    raw = subprocess.run(
        ["git", "-C", repo, "log", branch, "--since", since,
         "--pretty=@@@%H|%aI|%s", "--name-only"],
        capture_output=True, text=True).stdout
    commits, cur = [], None
    for line in raw.split("\n"):
        if line.startswith("@@@"):
            h, d, s = line[3:].split("|", 2)
            cur = {"sha": h, "date": d, "subject": s, "files": []}
            commits.append(cur)
        elif line.strip() and cur is not None:
            cur["files"].append(line.strip())
    for c in commits:
        c["dt"] = datetime.datetime.fromisoformat(c["date"])
        c["src"] = [f for f in c["files"] if SRC.match(f)]
    commits.sort(key=lambda c: c["dt"])
    return commits

def label(commits, window_days=7, hot_threshold=15):
    cands = [c for c in commits if c["src"] and not c["subject"].startswith("Merge ")]
    churn = collections.Counter(f for c in cands for f in c["src"])
    hot = {f for f, n in churn.items() if n >= hot_threshold}

    out = []
    for i, c in enumerate(cands):
        if FIXPAT.search(c["subject"]):        # 규칙 E: fix 커밋은 모집단에서 제외
            continue
        mine = set(c["src"]) - hot
        if not mine:
            continue
        deadline = c["dt"] + datetime.timedelta(days=window_days)
        verdict, reason, culprit = "OK", None, None
        for later in cands[i+1:]:
            if later["dt"] > deadline:
                break
            if not FIXPAT.search(later["subject"]):
                continue
            if mine & (set(later["src"]) - hot):
                verdict = "BROKE"
                reason = "revert" if later["subject"].lower().startswith("revert") else "fix_followup"
                culprit = later["sha"]
                break
        out.append({
            "sha": c["sha"], "parent_sha": None, "date": c["date"],
            "subject": c["subject"], "changed_files": sorted(mine),
            "all_changed_files": c["files"],
            "label": verdict, "label_reason": reason, "culprit_sha": culprit,
        })

    # 관측 미완 구간 제외
    if commits:
        cutoff = commits[-1]["dt"] - datetime.timedelta(days=window_days)
        out = [r for r in out if datetime.datetime.fromisoformat(r["date"]) <= cutoff]
    return out, hot

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default="target/umami")
    p.add_argument("--branch", default="origin/dev")
    p.add_argument("--since", default="2025-07-01")
    p.add_argument("--window", type=int, default=7)
    p.add_argument("--hot-threshold", type=int, default=15)
    p.add_argument("--out", default="data/changes.jsonl")
    a = p.parse_args()

    commits = load_commits(a.repo, a.branch, a.since)
    rows, hot = label(commits, a.window, a.hot_threshold)

    # parent_sha 채우기 (Phase 2에서 base 상태 비교용)
    for r in rows:
        r["parent_sha"] = subprocess.run(
            ["git", "-C", a.repo, "rev-parse", f"{r['sha']}^"],
            capture_output=True, text=True).stdout.strip() or None

    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dist = collections.Counter(r["label"] for r in rows)
    n = len(rows)
    print(f"n={n} BROKE={dist['BROKE']} ({dist['BROKE']*100/max(n,1):.1f}%) OK={dist['OK']}")
    print(f"고빈도 파일 제외: {len(hot)}개")
    print("사유:", collections.Counter(r["label_reason"] for r in rows if r["label_reason"]))