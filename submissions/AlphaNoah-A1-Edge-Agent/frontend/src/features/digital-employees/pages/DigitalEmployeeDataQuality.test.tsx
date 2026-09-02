import {
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../../../i18n/I18nContext";
import {
  PREFERENCES_STORAGE_KEY,
} from "../../../preferences/preferences";
import { PreferencesProvider } from "../../../preferences/PreferencesContext";
import {
  DigitalEmployeeReadError,
  type DigitalEmployeeCollection,
  type DigitalEmployeeDataSource,
} from "../types";
import { mockDigitalEmployeeCollection } from "../mock/mockDigitalEmployees";
import { DigitalEmployeeProvider } from "../provider/DigitalEmployeeProvider";
import { DigitalEmployeeDetailPage } from "./DigitalEmployeeDetailPage";
import { DigitalEmployeeListPage } from "./DigitalEmployeeListPage";

function sourceFor(
  collection: DigitalEmployeeCollection | null,
  read: DigitalEmployeeDataSource["getEmployees"] = vi
    .fn()
    .mockResolvedValue(collection),
): DigitalEmployeeDataSource {
  return {
    source: "mock",
    getInitialCollection: () => collection,
    getEmployees: read,
  };
}

function renderFeature(
  route: string,
  source: DigitalEmployeeDataSource,
) {
  window.localStorage.setItem(
    PREFERENCES_STORAGE_KEY,
    JSON.stringify({
      locale: "en-US",
      theme: "light",
      motion: "reduced",
    }),
  );

  return render(
    <PreferencesProvider>
      <I18nProvider>
        <DigitalEmployeeProvider dataSource={source}>
          <MemoryRouter initialEntries={[route]}>
            <Routes>
              <Route
                path="/employees"
                element={<DigitalEmployeeListPage />}
              />
              <Route
                path="/employees/:id"
                element={<DigitalEmployeeDetailPage />}
              />
            </Routes>
          </MemoryRouter>
        </DigitalEmployeeProvider>
      </I18nProvider>
    </PreferencesProvider>,
  );
}

describe("Digital Employee data quality presentation", () => {
  it("distinguishes a confirmed zero metric from an unknown null metric", async () => {
    const material = mockDigitalEmployeeCollection.employees.find(
      ({ id }) => id === "material-flow",
    );
    if (!material) {
      throw new Error("Expected material-flow fixture.");
    }
    const collection: DigitalEmployeeCollection = {
      ...mockDigitalEmployeeCollection,
      employees: [
        {
          ...material,
          todayMetrics: {
            ...material.todayMetrics,
            handled: 0,
            pending: null,
          },
        },
      ],
    };
    renderFeature("/employees/material-flow", sourceFor(collection));

    await screen.findByRole("heading", {
      name: "Material Flow Agent",
    });
    expect(
      screen.getByText("Handled today").parentElement,
    ).toHaveTextContent(/^Handled today0$/);
    expect(
      screen.getByText("Pending today").parentElement,
    ).toHaveTextContent(/^Pending todayUnknown$/);
  });

  it("shows an explicit empty state for an available empty collection", async () => {
    const collection: DigitalEmployeeCollection = {
      ...mockDigitalEmployeeCollection,
      employees: [],
    };
    renderFeature("/employees", sourceFor(collection));

    expect(
      await screen.findByText("No digital employees in this source"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The collection was read successfully and contains no roles.",
      ),
    ).toBeInTheDocument();
  });

  it("shows an explicit unavailable state and does not fall back to Mock", async () => {
    const source = sourceFor(
      null,
      vi.fn().mockRejectedValue(
        new DigitalEmployeeReadError(
          "unavailable",
          "mock",
          "Unavailable",
        ),
      ),
    );
    renderFeature("/employees", source);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Digital employee collection unavailable",
    );
    expect(alert).toHaveTextContent(
      "No Mock fallback was used",
    );
    expect(
      screen.queryByText("Equipment Maintenance Agent"),
    ).not.toBeInTheDocument();
  });

  it("announces a partial collection instead of relying on blank or inferred values", async () => {
    const collection: DigitalEmployeeCollection = {
      ...mockDigitalEmployeeCollection,
      quality: {
        availability: "partial",
        unknownFields: ["employees[2].todayMetrics.pending"],
        contractWarnings: ["One metric is unavailable."],
      },
    };
    renderFeature("/employees", sourceFor(collection));

    await screen.findByRole("heading", {
      name: "Digital Employee Center",
    });
    await waitFor(() =>
      expect(document.body).toHaveTextContent(
        /partial|some fields? (?:are|is) unavailable|incomplete/i,
      ),
    );
  });
});
