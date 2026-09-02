jest.mock("next/navigation", () => ({
  redirect: jest.fn(),
}));

import { redirect } from "next/navigation";
import Home from "../page";

describe("Home page", () => {
  it("uses the dashboard as the default product entry", () => {
    Home();
    expect(redirect).toHaveBeenCalledWith("/dashboard");
  });
});
