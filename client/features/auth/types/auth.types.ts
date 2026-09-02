export interface AuthUser {
  id: string;
  email: string;
  fullName: string;
  role: string;
  isActive: boolean;
  avatarUrl: string | null;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
}

export interface LoginRequest {
  email: string;
  password: string;
  rememberMe: boolean;
}

export interface LoginResponse extends AuthTokens {
  user: AuthUser;
}

export interface RegisterRequest {
  fullName: string;
  email: string;
  password: string;
  acceptTerms: boolean;
  receiveUpdates: boolean;
}

export interface RegisterResponse extends AuthTokens {
  user: AuthUser;
}

export interface ForgotPasswordRequest {
  email: string;
}

export interface ForgotPasswordResponse {
  success: boolean;
  message: string;
}

export interface RefreshTokenRequest {
  refreshToken: string;
}

export interface RefreshTokenResponse extends AuthTokens {}

export interface LogoutRequest {
  refreshToken: string | null;
}

export interface LogoutResponse {
  message: string;
}

export type CurrentUserResponse = AuthUser;

export interface AuthSession extends AuthTokens {
  user: AuthUser;
}
