interface ZAFRequestOptions {
  url: string;
  type: "GET" | "POST";
  contentType: string;
  data?: string;
  headers: Record<string, string>;
  secure: boolean;
  timeout: number;
}

interface ZAFClientInstance {
  context(): Promise<{ ticketId?: number | string }>;
  get(paths: string[]): Promise<Record<string, unknown>>;
  request<T>(options: ZAFRequestOptions): Promise<T>;
  invoke(name: string, payload: Record<string, unknown>): Promise<unknown>;
}

declare const ZAFClient: {
  init(): ZAFClientInstance;
};
