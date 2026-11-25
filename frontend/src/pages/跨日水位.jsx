import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 核证跨日水位() {
  const [现场, set现场] = useState(null);
  const [封印, set封印] = useState([]);
  const [手续, set手续] = useState([]);
  const [键, set键] = useState("");
  const [日, set日] = useState("2026-11-01");
  const [批, set批] = useState("");
  const [手, set手] = useState("");
  const [讯, set讯] = useState("");

  const 刷新 = async () => {
    set现场(await api.核证跨日水位(键));
    set封印(await api.封印());
    set手续(await api.封印手续());
  };

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const 做 = (f) => async () => {
    set讯("");
    try {
      const r = await f();
      set讯(`完成：${JSON.stringify(r)}`);
      await 刷新();
    } catch (e) {
      set讯(String(e.message || e));
    }
  };

  const 水 = (现场 && 现场.水位) || [];
  return (
    <div>
      <h1 className="题">跨日水位账核证</h1>
      <p className="述">
        甲口径 · <b>水位钉价值日</b>：跨日迟到净额只进价值日正式镜，到达日不新增；价值日已封印须持解封手续方可动，否则整笔拒绝。每笔跨日迟到必有水位账（水位号 / 归属日 / valid）。
      </p>

      <div className="段">
        <h2 className="段题">水位账（只读核证）</h2>
        <div className="行">
          <input value={键} onChange={(e) => set键(e.target.value)} placeholder="按水位号/流水号/账户筛选，可空" />
          <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
        </div>
        {现场 ? (
          <p className="述">
            钉法：{现场.钉法} · 核证 valid：<span className={`徽章 ${现场.valid ? "通" : "败"}`}>{现场.valid ? "有效" : "无效"}</span>
          </p>
        ) : null}
        {!水.length ? (
          <div className="空态">暂无跨日水位账</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>水位号</th>
                <th>流水号</th>
                <th>账户</th>
                <th>价值日</th>
                <th>到达营业日</th>
                <th>归属日</th>
                <th>状态</th>
                <th>valid</th>
                <th>装载批</th>
                <th>结算批</th>
              </tr>
            </thead>
            <tbody>
              {水.map((r) => (
                <tr key={r.水位号}>
                  <td>{r.水位号}</td>
                  <td>{r.流水号}</td>
                  <td>{r.账户键}</td>
                  <td>{r.价值日}</td>
                  <td>{r.到达营业日}</td>
                  <td><b>{r.归属日}</b></td>
                  <td><span className={`徽章 ${r.状态 === "已归位" ? "通" : "败"}`}>{r.状态}</span></td>
                  <td>{r.valid ? "1" : "0"}</td>
                  <td>{r.装载批次编号 || "—"}</td>
                  <td>{r.结算批次编号 || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="段">
        <h2 className="段题">营业日封印与解封（解封须持手续）</h2>
        <div className="行">
          <input value={日} onChange={(e) => set日(e.target.value)} placeholder="YYYY-MM-DD" />
          <input value={批} onChange={(e) => set批(e.target.value)} placeholder="批次编号，可空" />
          <input value={手} onChange={(e) => set手(e.target.value)} placeholder="解封手续编号（解封必填）" />
          <button onClick={做(() => api.执行封印(日, 批, 手))}>封印</button>
          <button className="次" onClick={做(() => api.执行解封(日, 批, 手, "台面解封"))}>解封</button>
        </div>
        {讯 ? <p className="讯">{讯}</p> : null}
        {!封印.length ? (
          <div className="空态">尚无封印营业日</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>营业日</th>
                <th>状态</th>
                <th>封印批</th>
                <th>封印时刻</th>
                <th>解封批</th>
                <th>解封手续</th>
              </tr>
            </thead>
            <tbody>
              {封印.map((r) => (
                <tr key={r.营业日}>
                  <td>{r.营业日}</td>
                  <td><span className={`徽章 ${r.状态 === "已封印" ? "败" : "通"}`}>{r.状态}</span></td>
                  <td>{r.封印批次编号 || "—"}</td>
                  <td>{r.封印时刻 || "—"}</td>
                  <td>{r.解封批次编号 || "—"}</td>
                  <td>{r.解封手续 || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="段">
        <h2 className="段题">封印手续流水</h2>
        {!手续.length ? (
          <div className="空态">尚无手续记录</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>营业日</th>
                <th>动作</th>
                <th>手续编号</th>
                <th>理由</th>
                <th>批次</th>
                <th>时刻</th>
              </tr>
            </thead>
            <tbody>
              {手续.map((r) => (
                <tr key={r.编号}>
                  <td>{r.营业日}</td>
                  <td>{r.动作}</td>
                  <td>{r.手续编号 || "—"}</td>
                  <td>{r.理由 || "—"}</td>
                  <td>{r.批次编号 || "—"}</td>
                  <td>{r.时刻}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
