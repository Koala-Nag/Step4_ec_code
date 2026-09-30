// 拠点の入力欄（F-809）。登録と編集で同じ欄を使う（R-32）。
// ★都道府県は47からの選択式（自由入力にしない。BR-05a の判定に使う。要件 6.3）。
import type { LocationDetail } from "@/lib/api/promo";

const WEEK = ["日", "月", "火", "水", "木", "金", "土"];

export function LocationFields({ loc, prefectures, disabled = false }: {
  loc: Partial<LocationDetail> | null;
  prefectures: { pref_code: string; name: string }[];
  disabled?: boolean;
}) {
  const days = loc?.weekdays ?? [1, 2, 3, 4, 5, 6, 0];
  return (
    <>
      <label>名称<input name="name" defaultValue={loc?.name ?? ""} maxLength={50} required disabled={disabled} /></label>
      <label>都道府県
        <select name="pref_code" defaultValue={loc?.pref_code ?? "13"} disabled={disabled}>
          {prefectures.map((p) => <option key={p.pref_code} value={p.pref_code}>{p.name}</option>)}
        </select>
      </label>
      <label>郵便番号<input name="zip" defaultValue={loc?.zip ?? ""} placeholder="1600023" required disabled={disabled} /></label>
      <label className="wide">住所<input name="address" defaultValue={loc?.address ?? ""} maxLength={100} required disabled={disabled} /></label>
      <label>電話番号<input name="tel" defaultValue={loc?.tel ?? ""} placeholder="0320000099" required disabled={disabled} /></label>
      <label>出荷の締め時刻<input type="time" name="cutoff_time" defaultValue={loc?.cutoff_time ?? "15:00"} required disabled={disabled} /></label>
      <fieldset className="wide">
        <legend>営業する曜日（BR-23。締め時刻を過ぎた出荷指示は、次に営業する日の発送になります）</legend>
        {[1, 2, 3, 4, 5, 6, 0].map((d) => (
          <label key={d} style={{ marginRight: 12 }}>
            <input type="checkbox" name="weekday" value={d} defaultChecked={days.includes(d)} disabled={disabled} /> {WEEK[d]}
          </label>
        ))}
      </fieldset>
    </>
  );
}

export const LOCATION_ERR: Record<string, string> = {
  name: "名称", pref_code: "都道府県", zip: "郵便番号（数字7桁）", address: "住所", tel: "電話番号（数字10〜11桁）",
  business_days: "営業する曜日（1つ以上）", cutoff_time: "締め時刻", location_code: "拠点コード（半角英数10文字まで）",
  kind: "区分", holiday: "休業日",
};
