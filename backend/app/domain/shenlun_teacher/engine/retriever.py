# -*- coding: utf-8 -*-
"""纯 Python TF-IDF 字符 n-gram 检索器（零第三方依赖，替代 sklearn 路径）。"""

import math
import re

_SPLIT = re.compile(r"\s")


class Retriever:
    """char 1-2 gram TF-IDF 余弦检索。docs 为空时 search 恒返回 []。"""

    def __init__(self, docs):
        self.docs = docs
        n = len(docs)
        self.idf = {}
        self.doc_vecs = []
        self.doc_norms = []
        if n == 0:
            return
        df = {}
        vecs = []
        for d in docs:
            counts = {}
            for g in self._grams(d):
                counts[g] = counts.get(g, 0) + 1
            vecs.append(counts)
            for g in counts:
                df[g] = df.get(g, 0) + 1
        self.idf = {g: math.log((n + 1) / (c + 1)) + 1.0 for g, c in df.items()}
        self.doc_vecs = vecs
        for counts in vecs:
            norm = math.sqrt(sum((c * self.idf.get(g, 1.0)) ** 2 for g, c in counts.items()))
            self.doc_norms.append(norm or 1.0)

    @staticmethod
    def _grams(text):
        t = _SPLIT.sub("", text or "")
        grams = list(t)
        grams.extend(t[i:i + 2] for i in range(len(t) - 1))
        return grams

    def search(self, query, top_k=5, min_score=0.05):
        if not self.docs:
            return []
        qc = {}
        for g in self._grams(query):
            qc[g] = qc.get(g, 0) + 1
        qnorm = math.sqrt(sum((c * self.idf.get(g, 1.0)) ** 2 for g, c in qc.items())) or 1.0
        scores = []
        for i, counts in enumerate(self.doc_vecs):
            common = qc.keys() & counts.keys()
            if not common:
                continue
            dot = sum(qc[g] * counts[g] * self.idf[g] * self.idf[g] for g in common)
            score = dot / (qnorm * self.doc_norms[i])
            if score > min_score:
                scores.append((i, score))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]
