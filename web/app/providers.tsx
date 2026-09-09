"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  getProfile,
  login as apiLogin,
  logout as apiLogout,
  tryRefresh,
  type UserProfile,
} from "@/lib/api";

interface AuthState {
  user: UserProfile | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  const loadProfile = useCallback(async () => {
    try {
      setUser(await getProfile());
    } catch {
      setUser(null);
    }
  }, []);

  // On mount the access token is gone (it lives in memory only), so the
  // stored refresh token is exchanged for a new one. This is what makes a
  // page reload keep the user signed in.
  useEffect(() => {
    (async () => {
      if (await tryRefresh()) await loadProfile();
      setLoading(false);
    })();
  }, [loadProfile]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      await apiLogin(email, password);
      await loadProfile();
    },
    [loadProfile],
  );

  const signOut = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, signIn, signOut, refresh: loadProfile }),
    [user, loading, signIn, signOut, loadProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
