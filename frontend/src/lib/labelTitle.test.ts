import { describe, expect, it } from "vitest";
import { parseTitle } from "./labelTitle";

describe("parseTitle", () => {
  it("splits a DailyMed title into name, generic name, form and maker", () => {
    expect(
      parseTitle("LIPITOR (ATORVASTATIN CALCIUM) TABLET, FILM COATED [VIATRIS SPECIALTY LLC]"),
    ).toEqual({
      name: "Lipitor",
      generic: "atorvastatin calcium",
      form: "Tablet, film coated",
      maker: "Viatris Specialty LLC",
    });
  });

  it("keeps acronyms of company names in capitals", () => {
    expect(parseTitle("METFORMIN (METFORMIN HCL) TABLET [QPHARMA, INC.]")?.maker).toBe(
      "Qpharma, INC.",
    );
  });

  it("works without a maker", () => {
    expect(parseTitle("OZEMPIC (SEMAGLUTIDE) INJECTION, SOLUTION")).toEqual({
      name: "Ozempic",
      generic: "semaglutide",
      form: "Injection, solution",
      maker: "",
    });
  });

  it("gives null for an empty title", () => {
    expect(parseTitle("")).toBeNull();
  });

  it("gives the first name for a title of several products", () => {
    expect(
      parseTitle(
        "OZEMPIC (ORAL SEMAGLUTIDE) TABLET RYBELSUS (ORAL SEMAGLUTIDE) TABLET [NOVO NORDISK PHARMACEUTICAL INDUSTRIES, LP]",
      ),
    ).toEqual({
      name: "Ozempic",
      generic: "oral semaglutide",
      form: "Several products",
      maker: "Novo Nordisk Pharmaceutical Industries, LP",
    });
    expect(parseTitle("MOUNJARO (TIRZEPATIDE) INJECTION [ELI LILLY AND COMPANY]")?.maker).toBe(
      "Eli Lilly and Company",
    );
  });

  it("splits a title without a generic name at the dosage form", () => {
    expect(
      parseTitle("METFORMIN HYDROCHLORIDE TABLET, FILM COATED [A-S MEDICATION SOLUTIONS]"),
    ).toEqual({
      name: "Metformin Hydrochloride",
      generic: "",
      form: "Tablet, film coated",
      maker: "A-S Medication Solutions",
    });
    expect(parseTitle("METFORMIN HCL TABLET [QPHARMA, INC.]")?.name).toBe("Metformin HCL");
    expect(parseTitle("SOMETHING [MAKER]")).toMatchObject({ name: "Something", form: "" });
  });
});
