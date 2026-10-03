"""LLM-annotated (silver) labels for the gold candidates, written to data/gold/silver_llm.jsonl.

These are NOT human gold labels. They were produced by an LLM (Claude) reading only the item text (title and
lead) as a human labeller would see it in `gold label`, following docs/labeling_guide.md; the pipeline's
predictions and the sampling strata were not shown. A human checks a random subset and agreement (Cohen's
kappa) is reported alongside every silver result. See docs/ai_usage.md.

Format per line: "index|entity|event|sentiment|factuality|material"
  event: CE Credit Event, GEO Geopolitical, MAC Macroeconomic, MA Merger/Acquisition, REG Regulatory/Legal,
         CYB Cyber/Operational, ND Natural Disaster/Supply Chain, ERN Earnings, MGT Management Change,
         PL Product Launch, OTH Other
  sentiment: - 0 +   factuality: c a r d o   material: y n
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = {"CE": "Credit Event", "GEO": "Geopolitical", "MAC": "Macroeconomic", "MA": "Merger/Acquisition",
          "REG": "Regulatory/Legal", "CYB": "Cyber/Operational", "ND": "Natural Disaster/Supply Chain",
          "ERN": "Earnings", "MGT": "Management Change", "PL": "Product Launch", "OTH": "Other"}
SENT = {"-": -1, "0": 0, "+": 1}
FACT = {"c": "confirmed", "a": "announced", "r": "rumour", "d": "denied", "o": "opinion"}
ANNOTATOR = "claude-opus-5-5 (LLM, silver)"

LABELS = """
0|ADBE|MGT|0|c|n
1|NONE|OTH|0|o|n
2|OTHER|OTH|0|o|n
3|OTHER|PL|+|c|n
4|MACRO|CE|-|o|n
5|MACRO|REG|-|c|n
6|MACRO|ND|-|o|n
7|NONE|OTH|0|c|n
8|OTHER|OTH|-|c|n
9|LIN|OTH|0|c|n
10|MACRO|OTH|0|o|n
11|WFC|REG|0|a|n
12|GOOGL|OTH|0|o|n
13|MS|MGT|0|a|y
14|WMT|CYB|-|c|n
15|INTC|OTH|0|o|n
16|JNJ|CE|0|c|y
17|MACRO|MAC|+|c|n
18|SBUX|GEO|-|c|n
19|IBM|MA|0|c|n
20|BA|OTH|+|c|y
21|WFC|OTH|0|c|n
22|MACRO|MAC|0|a|n
23|MRK|ERN|+|c|y
24|MACRO|MAC|0|o|n
25|MSFT|PL|0|a|n
26|OTHER|CYB|-|c|n
27|MACRO|OTH|-|o|n
28|MACRO|GEO|-|c|y
29|F|OTH|+|a|n
30|JNJ|CE|0|c|y
31|NONE|OTH|0|o|n
32|MACRO|OTH|0|a|n
33|OTHER|ERN|+|c|n
34|OTHER|MA|+|c|n
35|OTHER|CYB|-|c|n
36|NONE|OTH|0|o|n
37|NONE|REG|-|c|n
38|NONE|OTH|-|o|n
39|MACRO|MAC|+|c|y
40|ORCL|CE|-|c|y
41|MACRO|OTH|0|o|n
42|UPS|PL|+|a|n
43|OTHER|OTH|+|c|n
44|MACRO|OTH|+|a|n
45|MACRO|MAC|-|c|y
46|OTHER|OTH|0|o|n
47|OTHER|PL|+|c|n
48|MACRO|CYB|-|c|n
49|NONE|ND|-|c|n
50|MACRO|MAC|-|c|n
51|JNJ|REG|+|a|y
52|OTHER|PL|+|c|n
53|GOOGL|PL|+|c|n
54|OTHER|PL|+|c|n
55|OTHER|CYB|-|c|n
56|OTHER|MA|+|c|n
57|MACRO|MAC|0|a|y
58|MACRO|OTH|+|c|n
59|SBUX|ERN|0|c|y
60|MACRO|GEO|-|c|y
61|NVDA|MA|+|c|n
62|T|ERN|0|c|y
63|F|OTH|-|c|n
64|HON|MA|0|c|y
65|MACRO|CE|-|o|n
66|MACRO|PL|0|c|n
67|OTHER|OTH|0|c|n
68|OTHER|ND|-|c|n
69|MACRO|MAC|0|o|n
70|OTHER|OTH|-|c|n
71|MACRO|ND|-|o|n
72|LMT|OTH|0|c|n
73|OTHER|OTH|+|o|n
74|OTHER|OTH|0|o|n
75|NEE|ERN|0|c|y
76|OTHER|CYB|-|c|n
77|MACRO|REG|0|c|n
78|OTHER|REG|-|c|n
79|MACRO|GEO|+|o|n
80|OTHER|CYB|-|c|n
81|OTHER|REG|+|c|n
82|NONE|GEO|-|c|n
83|C|PL|+|a|n
84|MACRO|CE|-|o|n
85|AAPL|OTH|-|o|n
86|OTHER|PL|+|a|n
87|OTHER|OTH|0|o|n
88|OTHER|PL|+|c|n
89|NONE|OTH|0|c|n
90|GOOGL|PL|+|c|n
91|NONE|OTH|0|o|n
92|MACRO|ND|-|o|n
93|OTHER|CYB|-|c|n
94|MACRO|MAC|+|o|n
95|GM|CYB|-|c|y
96|MACRO|ND|-|o|n
97|MACRO|MAC|0|c|n
98|NVDA|OTH|+|a|n
99|OTHER|CYB|-|c|n
100|OTHER|PL|0|r|n
101|NVDA|OTH|+|o|n
102|TSLA|PL|0|o|n
103|XOM|OTH|-|c|n
104|OTHER|MGT|0|c|n
105|NONE|REG|0|c|n
106|UPS|MGT|0|a|n
107|QCOM|ERN|+|c|y
108|UNH|REG|-|c|y
109|OTHER|OTH|-|o|n
110|NONE|CYB|0|o|n
111|AAPL|OTH|0|o|n
112|OTHER|PL|+|c|n
113|MACRO|GEO|-|c|n
114|OTHER|MGT|+|c|n
115|OTHER|CYB|-|c|n
116|OTHER|OTH|+|a|n
117|OTHER|OTH|-|c|n
118|NONE|OTH|0|a|n
119|MACRO|ND|-|c|n
120|MSFT|OTH|0|o|n
121|OTHER|REG|-|c|n
122|SBUX|GEO|-|c|n
123|MS|ERN|0|c|y
124|MACRO|MAC|-|o|n
125|OTHER|CYB|-|c|n
126|AMZN|PL|+|a|n
127|MACRO|MAC|0|a|n
128|MACRO|MAC|0|c|n
129|JPM|PL|+|a|n
130|MSFT|PL|+|c|n
131|BRK-B|REG|+|c|n
132|WMT|PL|+|c|n
133|CFG|OTH|+|a|n
134|NKE|OTH|-|a|n
135|MACRO|MAC|-|c|y
136|NONE|OTH|0|o|n
137|OTHER|OTH|0|o|n
138|AMZN|REG|0|c|n
139|MACRO|MAC|-|o|n
140|OTHER|CYB|-|c|n
141|DIS|MGT|0|c|y
142|MACRO|REG|0|o|n
143|GOOGL|PL|+|c|n
144|ORCL|ND|+|c|n
145|TSLA|REG|-|o|n
146|ORCL|OTH|0|o|n
147|OTHER|PL|+|a|n
148|OTHER|CYB|-|c|n
149|XOM|REG|0|c|y
150|NVDA|PL|+|a|n
151|MACRO|ND|0|o|n
152|PG|OTH|-|a|n
153|AAPL|OTH|-|o|n
154|MACRO|MAC|+|c|y
155|F|GEO|-|o|n
156|TGT|PL|+|c|n
157|OTHER|CYB|-|c|n
158|LLY|OTH|0|c|n
159|NONE|OTH|0|o|n
160|T|CYB|-|c|n
161|OTHER|CYB|-|c|n
162|NONE|OTH|-|c|n
163|OTHER|OTH|0|o|n
164|BA|OTH|+|c|y
165|OTHER|OTH|0|o|n
166|BNY|OTH|+|o|n
167|MACRO|MAC|0|o|n
168|BA|CYB|-|c|y
169|MACRO|OTH|-|o|n
170|AAPL|OTH|0|r|n
171|NONE|OTH|0|o|n
172|OTHER|CYB|-|c|n
173|OTHER|PL|+|c|n
174|RF|OTH|0|c|n
175|OTHER|MGT|-|c|n
176|OTHER|CYB|-|c|n
177|MACRO|REG|0|a|n
178|BAC|ERN|0|c|y
179|CAT|GEO|-|c|y
180|MACRO|MAC|+|c|n
181|NONE|OTH|0|c|n
182|OTHER|CYB|-|c|n
183|NKE|OTH|-|o|n
184|NONE|OTH|0|c|n
185|ADBE|OTH|0|c|n
186|AAPL|OTH|+|c|n
187|OTHER|CYB|-|c|n
188|MACRO|OTH|0|o|n
189|BA|OTH|+|c|y
190|AAPL|CYB|-|c|n
191|TSLA|OTH|-|o|n
192|LLY|OTH|+|a|n
193|MACRO|ND|0|c|n
194|OTHER|OTH|+|c|n
195|OTHER|CYB|+|c|n
196|OTHER|PL|+|a|n
197|LMT|MGT|0|c|n
198|GS|ERN|+|c|y
199|MACRO|MAC|0|o|n
200|NONE|OTH|+|c|n
201|MACRO|MAC|+|a|n
202|NONE|ND|-|c|n
203|MACRO|MAC|0|a|n
204|MACRO|MAC|0|c|n
205|AMD|OTH|+|o|n
206|MACRO|MAC|-|c|n
207|MSFT|OTH|+|o|n
208|MACRO|MAC|-|o|n
209|MSFT|PL|0|a|n
210|HBAN|MA|+|c|y
211|OTHER|MA|-|c|n
212|NONE|OTH|0|o|n
213|MACRO|REG|0|a|n
214|MACRO|OTH|-|c|n
215|NONE|OTH|0|c|n
216|OTHER|CYB|0|o|n
217|OTHER|OTH|+|o|n
218|ZION|CE|-|c|y
219|IBM|OTH|+|c|n
220|DIS|OTH|0|c|n
221|BA|CYB|-|c|y
222|PEP|OTH|0|o|n
223|MACRO|OTH|0|o|n
224|OTHER|PL|+|a|n
225|TSLA|ND|-|c|n
226|IBM|MGT|0|o|n
227|MACRO|GEO|-|c|y
228|META|OTH|0|o|n
229|OTHER|CYB|-|c|n
230|OTHER|PL|+|a|n
231|DUK|ERN|0|c|y
232|OTHER|CYB|0|o|n
233|F|ND|-|c|y
234|NONE|OTH|0|c|n
235|OTHER|OTH|0|c|n
236|MACRO|OTH|0|o|n
237|AMZN|PL|+|a|n
238|MSFT|CYB|-|c|y
239|MACRO|MAC|-|c|y
240|IBM|ERN|0|c|y
241|OTHER|OTH|+|o|n
242|T|OTH|+|o|n
243|OTHER|CYB|-|c|n
244|MACRO|MAC|-|c|n
245|GOOGL|PL|+|c|n
246|NONE|ND|-|a|n
247|CAT|OTH|+|o|n
248|TSLA|OTH|+|c|n
249|OTHER|CYB|-|r|n
250|OTHER|REG|-|c|n
251|META|OTH|-|o|n
252|SCHW|MA|0|a|n
253|OTHER|CYB|0|c|n
254|PNC|ERN|0|c|n
255|OTHER|OTH|+|c|n
256|TGT|OTH|0|o|n
257|TSLA|OTH|-|o|n
258|OTHER|MGT|-|c|n
259|WAL|CE|+|c|y
260|OTHER|PL|+|a|n
261|USB|OTH|0|c|n
262|OTHER|MAC|-|o|n
263|OTHER|MGT|-|r|n
264|OTHER|CE|-|c|n
265|COF|REG|+|c|n
266|GOOGL|PL|0|c|n
267|GS|OTH|0|c|n
268|NONE|OTH|0|o|n
269|NONE|OTH|-|c|n
270|PEP|OTH|0|c|n
271|HON|MGT|0|a|n
272|MACRO|REG|+|a|n
273|OTHER|ERN|0|c|n
274|T|OTH|+|a|n
275|MACRO|MAC|+|c|y
276|UNH|PL|+|a|n
277|AXP|OTH|+|c|n
278|MACRO|MAC|-|c|y
279|OTHER|CYB|-|c|n
280|GOOGL|PL|0|c|n
281|GOOGL|OTH|+|o|n
282|BA|OTH|0|c|n
283|MACRO|GEO|-|o|n
284|MSFT|OTH|+|o|n
285|OTHER|CE|-|c|y
286|MACRO|REG|0|o|n
287|LIN|ERN|0|c|y
288|XOM|OTH|-|c|n
289|MACRO|MAC|+|c|n
290|DIS|OTH|-|o|n
291|WMT|CYB|-|c|n
292|MACRO|CE|-|o|n
293|WFC|OTH|+|c|n
294|CAT|MGT|0|c|n
295|KEY|OTH|0|c|n
"""

NOTES = {
    4: "conditional warning, no event happened: labelled by topic, factuality opinion",
    40: "CDS at a record: market-priced credit stress, labelled Credit Event",
    58: "rating upgrade: the guide lists downgrades under Credit Event, upgrades go to Other",
    179: "tariff impact on results: Geopolitical (cause) chosen over Earnings (guidance)",
    187: "Pearson Ford is a car dealership, not Ford Motor",
    225: "ambiguous: product reveal delayed by weather; Natural Disaster chosen over Product Launch",
    259: "bank-run context; the statement itself reads reassuring, so sentiment +",
}


def main() -> int:
    lines = (ROOT / "data" / "gold" / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
    candidates = [json.loads(line) for line in lines if line.strip()]
    out = ROOT / "data" / "gold" / "silver_llm.jsonl"
    rows = []
    for line in LABELS.strip().splitlines():
        i, entity, event, sentiment, factuality, material = line.split("|")
        item = candidates[int(i)]
        rows.append({
            "key": item["key"], "document_id": item.get("document_id"), "published_at": item.get("published_at"),
            "split": item["split"], "stratum": item["stratum"], "source": item["source"], "title": item["title"],
            "entity": entity, "event_type": EVENTS[event], "sentiment": SENT[sentiment],
            "factuality": FACT[factuality], "material": material == "y", "note": NOTES.get(int(i), ""),
            "annotator": ANNOTATOR, "labeled_at": datetime.now(UTC).isoformat(),
        })
    if len({r["key"] for r in rows}) != len(rows):
        print("duplicate item index", file=sys.stderr)
        return 1
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {len(rows)} silver labels to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
