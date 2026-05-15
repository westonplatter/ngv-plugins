export interface TestCase {
  name: string;
  input: string;
  shouldFlag: boolean;
  expectedCategories: string[];
}

export const TEST_CASES: TestCase[] = [
  {
    name: "account_id_leak",
    input: [
      "# Sample IBKR account snippet",
      "account_id: U8675309",
      "currency: USD",
    ].join("\n") + "\n",
    shouldFlag: true,
    expectedCategories: ["account-id"],
  },
  {
    name: "account_id_clean_placeholder",
    input: [
      "# Sample IBKR account snippet",
      "account_id: U1234567",
      "currency: USD",
    ].join("\n") + "\n",
    shouldFlag: false,
    expectedCategories: [],
  },
];
