import { errorMessage } from "../utils/error";
import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";

interface RegisterPageProps {
  onNavigateToLogin: () => void;
}

export const RegisterPage: React.FC<RegisterPageProps> = ({ onNavigateToLogin }) => {
  const { capabilities } = useAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const isClosed = capabilities && capabilities.registration_mode !== "open";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    // Валидация на клиенте
    if (username.trim().length < 3) {
      setError("Имя пользователя должно содержать не менее 3 символов.");
      return;
    }

    if (password.length < 8) {
      setError("Длина пароля должна быть не менее 8 символов.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Введенные пароли не совпадают.");
      return;
    }

    setLoading(true);

    try {
      const res = await api.register({
        username: username.trim(),
        email: email.trim(),
        password,
        confirm_password: confirmPassword,
      });

      setSuccess(
        res.email_verification_required
          ? "Регистрация успешна! На указанный email направлено письмо с подтверждением."
          : "Учётная запись успешно зарегистрирована! Теперь вы можете войти в систему."
      );

      // Через 2 секунды перенаправляем на вход
      setTimeout(() => {
        onNavigateToLogin();
      }, 2000);
    } catch (err: unknown) {
      setError(errorMessage(err, "Ошибка при регистрации учётной записи."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="w-12 h-12 bg-blue-600 rounded-xl mx-auto flex items-center justify-center text-white font-bold text-2xl shadow-md">
          A
        </div>
        <h2 className="mt-4 text-center text-3xl font-extrabold text-gray-900 tracking-tight">
          Регистрация в ALXPRGS SSO
        </h2>
        <p className="mt-2 text-center text-sm text-gray-600">
          Создание новой учётной записи для сервисов экосистемы{" "}
          <span className="font-semibold text-gray-800">alxprgs.tech</span>
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <div className="bg-white py-8 px-4 shadow-xl sm:rounded-xl sm:px-10 border border-gray-100">
          {isClosed ? (
            <div className="text-center py-6 space-y-4">
              <div className="w-12 h-12 mx-auto rounded-full bg-amber-100 text-amber-600 flex items-center justify-center font-bold text-xl">
                !
              </div>
              <h3 className="text-lg font-semibold text-gray-900">
                Самостоятельная регистрация закрыта
              </h3>
              <p className="text-sm text-gray-600 leading-relaxed">
                В настоящий момент свободная регистрация пользователей отключена администратором системы.
                Для получения доступа обратитесь к администратору организации.
              </p>
              <div className="pt-4">
                <button
                  type="button"
                  onClick={onNavigateToLogin}
                  className="w-full inline-flex justify-center py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 transition-colors"
                >
                  Вернуться на страницу входа
                </button>
              </div>
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-4 bg-red-50 border-l-4 border-red-500 p-3 rounded text-sm text-red-700">
                  {error}
                </div>
              )}

              {success && (
                <div className="mb-4 bg-green-50 border-l-4 border-green-500 p-3 rounded text-sm text-green-700">
                  {success}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700">
                    Имя пользователя (логин)
                  </label>
                  <div className="mt-1">
                    <input
                      type="text"
                      required
                      minLength={3}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="appearance-none block w-full px-3 py-2.5 border border-gray-300 rounded-lg shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
                      placeholder="alex_ivanov"
                    />
                  </div>
                  <p className="mt-1 text-xs text-gray-500">
                    От 3 до 50 символов (латинские буквы, цифры, _, -, .)
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700">Email адрес</label>
                  <div className="mt-1">
                    <input
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="appearance-none block w-full px-3 py-2.5 border border-gray-300 rounded-lg shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
                      placeholder="alex@alxprgs.tech"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700">Пароль</label>
                  <div className="mt-1">
                    <input
                      type="password"
                      required
                      minLength={8}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="appearance-none block w-full px-3 py-2.5 border border-gray-300 rounded-lg shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
                    />
                  </div>
                  <p className="mt-1 text-xs text-gray-500">Не менее 8 символов</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700">
                    Подтверждение пароля
                  </label>
                  <div className="mt-1">
                    <input
                      type="password"
                      required
                      minLength={8}
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      className="appearance-none block w-full px-3 py-2.5 border border-gray-300 rounded-lg shadow-sm placeholder-gray-400 focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm"
                    />
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={loading || Boolean(success)}
                    className="w-full flex justify-center py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 transition-colors"
                  >
                    {loading ? "Регистрация..." : "Зарегистрироваться"}
                  </button>
                </div>
              </form>

              <div className="mt-6 text-center">
                <span className="text-sm text-gray-600">Уже есть учётная запись? </span>
                <button
                  type="button"
                  onClick={onNavigateToLogin}
                  className="text-sm font-medium text-blue-600 hover:text-blue-500 focus:outline-none underline"
                >
                  Войти
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
