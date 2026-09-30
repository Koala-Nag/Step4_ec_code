// UT-900番台｜フロント（単体テスト仕様書 6章）。
//
// ★薄くする。判断はすべてバックエンドにある（N-35）。
//   ここで守るのは「画面の中だけで完結している判断」だけ。

import { countLabel, sizeState, yen } from "@/lib/view/format";
import { href } from "@/lib/view/list-url";

// --- UT-901 ★正常値 ------------------------------------------------
describe("UT-901 絞り込み・並び替えを変えると after が落ちる", () => {
  const base = { sort: "price_asc", category: "TSHIRT", after: "1990,P0001" };

  test("並び替えを変えると after が落ちる", () => {
    expect(href(base, { sort: "new", after: undefined })).toBe(
      "/products?sort=new&category=TSHIRT",
    );
  });

  test("絞り込みを変えると after が落ちる", () => {
    expect(href(base, { category: "SHIRT", after: undefined })).toBe(
      "/products?sort=price_asc&category=SHIRT",
    );
  });

  test("★patch で after を指定しなければ、そもそも引き継がれない", () => {
    // 「次の20件へ」だけが after を明示する。それ以外のリンクには付かない
    expect(href(base, { sort: "new" })).not.toContain("after");
    expect(href(base, { after: "2990,P0002" })).toContain("after=2990%2CP0002");
  });
});

// --- UT-902 正常値 --------------------------------------------------
test("UT-902 offset を1度も付けない", () => {
  // OFFSET は深いページで 1,408ms かかる（R-08）。キーセット方式にしてある
  const urls = [
    href({}, {}),
    href({ sort: "new" }, { category: "PANTS" }),
    href({ after: "1,X" }, { after: "2,Y" }),
    href({ page: "5" }, {}),          // 画面が page を送ってきても持ち回さない
  ];
  for (const u of urls) expect(u).not.toContain("offset");
  expect(urls[3]).toBe("/products");
});

// --- UT-903 ★境界値 ------------------------------------------------
describe("UT-903 サイズの3状態", () => {
  test("SKUの行があって在庫あり → ふつう", () => {
    expect(sizeState({ selectable: true })).toBe("ok");
  });
  test("SKUの行があって0点 → 品切れ", () => {
    expect(sizeState({ selectable: false })).toBe("sold");
  });
  test("★SKUの行が無い → 取り扱いなし（品切れと同じにしない）", () => {
    expect(sizeState(undefined)).toBe("none");
    expect(sizeState(null)).toBe("none");
    // 「もともと無い」と「いま売り切れ」が同じ値になっていないこと
    expect(sizeState(undefined)).not.toBe(sizeState({ selectable: false }));
  });
});

// --- UT-904 正常値 --------------------------------------------------
test("UT-904 金額の表示整形（計算はしない）", () => {
  expect(yen(2990)).toBe("¥2,990");
  expect(yen(0)).toBe("¥0");
  expect(yen(1234567)).toBe("¥1,234,567");
});

// --- UT-905 境界値 --------------------------------------------------
test("UT-905 件数の表示", () => {
  expect(countLabel(100, false)).toBe("100件");
  expect(countLabel(100, true)).toBe("100件以上");   // 101件目が見つかった
  expect(countLabel(0, false)).toBe("0件");          // 絞り込みが効いていることが分かる
});
