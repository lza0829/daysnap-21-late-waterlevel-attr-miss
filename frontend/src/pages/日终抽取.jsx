import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 日终抽取() {
  const [日, set日] = useState("2026-11-20");
  const [手, set手] = useState("");
  const [批, set批] = useState([]);
  const [讯, set讯] = useState("");

  const 刷新 = () => api.抽取批次().then(set批);

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  return (
    <div>
      <h1 className="题">日终抽取</h1>
      <p className="述">
        按营业日写周期快照：前日余额 + 当日流水净额。营业日已封印时须填写解封手续方可再抽；跨日迟到无水位账则抽取失败闭。
      </p>
      <div className="行">
        <input value={日} onChange={(e) => set日(e.target.value)} placeholder="YYYY-MM-DD" />
        <input value={手} onChange={(e) => set手(e.target.value)} placeholder="解封手续（已封印日必填）" />
        <button
          onClick={() =>
            api
              .抽取(日, "", 手)
              .then((r) => set讯(`批次 ${r.批次编号} 写入=${r.写入} 追加版本=${r.追加版本 ?? r.盖写} 迟到纠偏=${r.迟到纠偏 ?? 0} 水位归位=${r.水位归位 ?? 0} 断档=${r.断档}`))
              .then(刷新)
              .catch((e) => set讯(String(e.message || e)))
          }
        >
          执行抽取
        </button>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新批次</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}
      <div className="段">
        <h2 className="段题">抽取批次</h2>
        {!批.length ? (
          <div className="空态">尚无抽取</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>编号</th>
                <th>营业日</th>
                <th>时刻</th>
                <th>报告</th>
              </tr>
            </thead>
            <tbody>
              {批.map((r) => (
                <tr key={r.编号}>
                  <td>{r.编号}</td>
                  <td>{r.营业日}</td>
                  <td>{r.时刻}</td>
                  <td>{typeof r.报告 === "object" ? JSON.stringify(r.报告) : r.报告}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
