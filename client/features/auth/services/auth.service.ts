"use client";

import { apiClient } from "@/services/api/client";
import type {
  CurrentUserResponse,
  ForgotPasswordRequest,
  ForgotPasswordResponse,
  LoginRequest,
  LoginResponse,
  LogoutRequest,
  LogoutResponse,
  RefreshTokenRequest,
  RefreshTokenResponse,
  RegisterRequest,
  RegisterResponse,
} from "@/features/auth/types/auth.types";
import {
  mapBackendAuthResponse,
  mapBackendTokens,
  mapBackendUser,
  type BackendAuthDto,
  type BackendMessageDto,
  type BackendTokenDto,
  type BackendUserDto,
} from "@/features/auth/utils/auth-mappers";

export const authService = {
  async login(payload: LoginRequest): Promise<LoginResponse> {
    const { data } = await apiClient.post<BackendAuthDto>("/auth/login", {
      email: payload.email,
      password: payload.password,
    });

    return mapBackendAuthResponse(data);
  },

  async register(payload: RegisterRequest): Promise<RegisterResponse> {
    const { data } = await apiClient.post<BackendAuthDto>("/auth/register", {
      full_name: payload.fullName,
      email: payload.email,
      password: payload.password,
    });

    return mapBackendAuthResponse(data);
  },

  async forgotPassword(
    payload: ForgotPasswordRequest
  ): Promise<ForgotPasswordResponse> {
    const { data } = await apiClient.post<BackendMessageDto>(
      "/auth/forgot-password",
      {
        email: payload.email,
      }
    );

    return {
      success: true,
      message: data.message,
    };
  },

  async refreshToken(
    payload: RefreshTokenRequest
  ): Promise<RefreshTokenResponse> {
    const { data } = await apiClient.post<BackendTokenDto>("/auth/refresh", {
      refresh_token: payload.refreshToken,
    });

    return mapBackendTokens(data);
  },

  async logout(payload: LogoutRequest): Promise<LogoutResponse> {
    if (!payload.refreshToken) {
      return { message: "Logged out" };
    }

    const { data } = await apiClient.post<BackendMessageDto>("/auth/logout", {
      refresh_token: payload.refreshToken,
    });

    return { message: data.message };
  },

  async getMe(): Promise<CurrentUserResponse> {
    const { data } = await apiClient.get<BackendUserDto>("/auth/me");
    return mapBackendUser(data);
  },
};
