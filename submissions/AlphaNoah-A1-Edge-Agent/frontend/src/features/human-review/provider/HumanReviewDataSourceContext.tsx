import {
  createContext,
  useContext,
  type PropsWithChildren,
} from "react";

import type { HumanReviewDataSource } from "../models/humanReview";

const HumanReviewDataSourceContext =
  createContext<HumanReviewDataSource | null>(null);

interface HumanReviewProviderProps extends PropsWithChildren {
  dataSource: HumanReviewDataSource;
}

export function HumanReviewProvider({
  dataSource,
  children,
}: HumanReviewProviderProps) {
  return (
    <HumanReviewDataSourceContext.Provider value={dataSource}>
      {children}
    </HumanReviewDataSourceContext.Provider>
  );
}

export function useHumanReviewDataSource(): HumanReviewDataSource {
  const value = useContext(HumanReviewDataSourceContext);
  if (!value) {
    throw new Error(
      "Human review hooks must be used inside HumanReviewProvider",
    );
  }
  return value;
}
