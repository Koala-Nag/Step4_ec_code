/** 単体テスト（単体テスト仕様書 6章）。
 *
 * ★薄くする。判断はすべてバックエンドにある（N-35）ので、
 *   フロントの単体テストで守るものは多くない。
 * ★画面の見た目は結合テスト（IT-100番台）とシステムテストで見る。
 *   ここで DOM を描かないのは、そのため（jsdom を入れていない）。
 */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  testMatch: ["<rootDir>/__tests__/**/*.test.ts"],
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/$1" },
};
