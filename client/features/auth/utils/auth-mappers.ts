import type {
  AuthTokens,
  AuthUser,
  LoginResponse,
  RegisterResponse,
} from "@/features/auth/types/auth.types";

/** Backend user payload (snake_case). */
export interface BackendUserDto {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** Backend token pair (snake_case). */
export interface BackendTokenDto {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

/** Backend login/register response. */
export interface BackendAuthDto {
  user: BackendUserDto;
  tokens: BackendTokenDto;
}

export interface BackendMessageDto {
  message: string;
}

const AUTH_FIELD_ALIASES: Record<string, string> = {
  full_name: "fullName",
  refresh_token: "refreshToken",
  access_token: "accessToken",
  accept_terms: "acceptTerms",
  receive_updates: "receiveUpdates",
  remember_me: "rememberMe",
};

export function mapBackendUser(dto: BackendUserDto): AuthUser {
  return {
    id: String(dto.id),
    email: dto.email,
    fullName: dto.full_name,
    role: dto.role,
    isActive: dto.is_active,
    avatarUrl: null,
  };
}

export function mapBackendTokens(dto: BackendTokenDto): AuthTokens {
  return {
    accessToken: dto.access_token,
    refreshToken: dto.refresh_token,
  };
}

export function mapBackendAuthResponse(
  dto: BackendAuthDto
): LoginResponse & RegisterResponse {
  return {
    user: mapBackendUser(dto.user),
    ...mapBackendTokens(dto.tokens),
  };
}

export function mapAuthFieldName(field: string): string {
  return AUTH_FIELD_ALIASES[field] ?? field;
}
