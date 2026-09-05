/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'mock' (default) or 'live'. Selects the status data source. */
  readonly VITE_DATA_SOURCE?: 'mock' | 'live';
  /** Default mock scenario id when the data source is 'mock'. */
  readonly VITE_MOCK_SCENARIO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
