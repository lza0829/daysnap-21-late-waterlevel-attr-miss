import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 周期快照() {
  const [日, set日] = useState("");
  const [行, set行] = useState([]);
  const [含历史, 切历史] = useState(false);
  const [讯, set讯] = useState("");

  const 刷新 = () => {
    const qs = [];
    if (日) qs.push(`营业日=${encodeURIComponent(日)}`);
    if (含历史) qs.push("含历史=true");
    return api.快照(qs.length ? `?${qs.join("&")}` : "").then(set行);
  };

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, [含历史]);

  return (
    <div>
      <h1 className="题">周期快照</h1>
      <p className="述">
        默认只列当前版本镜（主读）；勾选「含历史版本」可看纠偏版本链——基线 v1
        永不改，迟到补抽只追加新版本。
      </p>
      <div className="行">
        <input value={日} onChange={(e) => set日(e.target.value)} placeholder="筛选营业日，可空" />
        <label className="行" style={{ marginBottom: 0, gap: "0.3rem" }}>
          <input type="checkbox" checked={含历史} onChange={(e) => 切历史(e.target.checked)} />
          含历史版本（纠偏链）
        </label>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}
      {!行.length ? (
        <div className="空态">暂无快照</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>账户键</th>
              <th>营业日</th>
              <th>版本</th>
              <th>余额</th>
              <th>当前</th>
              <th>前序</th>
              <th>抽取批次</th>
              <th>来源</th>
            </tr>
          </thead>
          <tbody>
            {行.map((r) => (
              <tr key={r.快照键}>
                <td>{r.账户键}</td>
                <td>{r.营业日}</td>
                <td>v{r.版本号}</td>
                <td>{r.余额}</td>
                <td>{r.是否当前 ? "当前" : "历史"}</td>
                <td>{r.前序快照键 || "—"}</td>
                <td>{r.抽取批次编号}</td>
                <td>{r.来源}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
