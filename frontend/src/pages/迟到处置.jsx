import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 迟到处置() {
  const [单, 置单] = useState([]);
  const [户, 置户] = useState("户甲");
  const [日, 置日] = useState("2026-11-20");
  const [镜, 置镜] = useState(null);
  const [讯, 置讯] = useState("");

  const 刷新单 = () => api.迟到处置().then(置单);
  const 取镜 = (视角) =>
    api
      .迟到镜(户, 日, 视角)
      .then(置镜)
      .catch((e) => 置讯(String(e.message || e)));

  useEffect(() => {
    刷新单().catch((e) => 置讯(String(e.message || e)));
    取镜("链").catch((e) => 置讯(String(e.message || e)));
  }, []);

  return (
    <div>
      <h1 className="题">流水迟到补抽 · 迟到处置</h1>
      <p className="述">
        基镜+纠偏版本链：基线有效行永不改，迟到追加纠偏版本并翻转当前；每笔迟到必有处置单（valid
        证据），禁止静默忽略、禁止无版本链盖写基行。
      </p>

      <div className="段">
        <h2 className="段题">迟到处置单（只读证据）</h2>
        {!单.length ? (
          <div className="空态">尚无迟到处置</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>流水号</th>
                <th>账户</th>
                <th>营业日</th>
                <th>状态</th>
                <th>valid</th>
                <th>基线余额</th>
                <th>前余额</th>
                <th>后余额</th>
                <th>纠偏版本</th>
                <th>级联</th>
                <th>装载批</th>
                <th>纠偏批</th>
              </tr>
            </thead>
            <tbody>
              {单.map((s) => (
                <tr key={s.编号}>
                  <td>{s.流水号}</td>
                  <td>{s.账户键}</td>
                  <td>{s.营业日}</td>
                  <td>
                    <span className={`徽章 ${s.状态 === "已纠偏" ? "通" : "败"}`}>{s.状态}</span>
                  </td>
                  <td>{s.valid}</td>
                  <td>{s.基线余额 ?? "—"}</td>
                  <td>{s.前余额 ?? "—"}</td>
                  <td>{s.后余额 ?? "—"}</td>
                  <td>{s.版本号 ?? "—"}</td>
                  <td>{s.级联 ? "第二笔+" : "首笔"}</td>
                  <td>{s.装载批次编号}</td>
                  <td>{s.纠偏批次编号 || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="段">
        <h2 className="段题">只读取镜：基线 / 当前 / 纠偏链（旧余额可否回看的口径分叉）</h2>
        <div className="行">
          <input value={户} onChange={(e) => 置户(e.target.value)} placeholder="账户键" />
          <input value={日} onChange={(e) => 置日(e.target.value)} placeholder="YYYY-MM-DD" />
          <button onClick={() => 取镜("基线")}>基线（v1 旧余额）</button>
          <button className="次" onClick={() => 取镜("当前")}>当前（主读）</button>
          <button className="次" onClick={() => 取镜("链")}>纠偏链（全版本回看）</button>
        </div>
        {讯 ? <p className="讯">{讯}</p> : null}
        {镜 ? (
          <div>
            <p className="述">
              视角：{镜.视角}
              {镜.视角 === "纠偏链" ? ` · 链长 ${镜.链长}` : ""}
              {!镜.存在 ? " · 该账日无快照" : ""}
            </p>
            {镜.镜 ? (
              <table>
                <thead>
                  <tr>
                    <th>快照键</th>
                    <th>版本号</th>
                    <th>余额</th>
                    <th>是否当前</th>
                    <th>抽取批次</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{镜.镜.快照键}</td>
                    <td>{镜.镜.版本号}</td>
                    <td>{镜.镜.余额}</td>
                    <td>{镜.镜.是否当前 ? "当前" : "历史"}</td>
                    <td>{镜.镜.抽取批次编号}</td>
                  </tr>
                </tbody>
              </table>
            ) : null}
            {镜.链 ? (
              <table>
                <thead>
                  <tr>
                    <th>版本</th>
                    <th>快照键</th>
                    <th>余额</th>
                    <th>当前</th>
                    <th>前序</th>
                    <th>抽取批次</th>
                  </tr>
                </thead>
                <tbody>
                  {镜.链.map((v) => (
                    <tr key={v.快照键}>
                      <td>v{v.版本号}</td>
                      <td>{v.快照键}</td>
                      <td>{v.余额}</td>
                      <td>{v.是否当前 ? "当前" : "历史"}</td>
                      <td>{v.前序快照键 || "—（基线）"}</td>
                      <td>{v.抽取批次编号}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
