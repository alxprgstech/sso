/**
 * Утилиты для работы с WebAuthn / Passkeys (W3C WebAuthn Level 3, G4-PASSKEY).
 * Обеспечивают сериализацию/десериализацию между Base64URL строками JSON-контракта сервера
 * и ArrayBuffer бинарных структур браузерного navigator.credentials API.
 */

export function bufferToBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

export function base64UrlToBuffer(base64url: string): ArrayBuffer {
  let base64 = base64url.replace(/-/g, "+").replace(/_/g, "/");
  while (base64.length % 4) {
    base64 += "=";
  }
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

export function prepareCreationOptions(serverOptions: any): CredentialCreationOptions {
  const opts = typeof serverOptions === "string" ? JSON.parse(serverOptions) : serverOptions;
  const rawPublicKey = opts.publicKey || opts;
  const publicKey = { ...rawPublicKey };

  if (typeof publicKey.challenge === "string") {
    publicKey.challenge = base64UrlToBuffer(publicKey.challenge);
  }

  if (publicKey.user && typeof publicKey.user.id === "string") {
    publicKey.user = {
      ...publicKey.user,
      id: base64UrlToBuffer(publicKey.user.id),
    };
  }

  if (Array.isArray(publicKey.excludeCredentials)) {
    publicKey.excludeCredentials = publicKey.excludeCredentials.map((c: any) => ({
      ...c,
      id: typeof c.id === "string" ? base64UrlToBuffer(c.id) : c.id,
    }));
  }

  return { publicKey };
}

export function serializeCreationResponse(cred: any): any {
  const response: any = {
    clientDataJSON: bufferToBase64Url(cred.response.clientDataJSON),
    attestationObject: bufferToBase64Url(cred.response.attestationObject),
  };
  if (typeof cred.response.getTransports === "function") {
    response.transports = cred.response.getTransports();
  }
  return {
    id: cred.id,
    rawId: bufferToBase64Url(cred.rawId),
    type: cred.type,
    response,
  };
}

export function prepareRequestOptions(serverOptions: any): CredentialRequestOptions {
  const opts = typeof serverOptions === "string" ? JSON.parse(serverOptions) : serverOptions;
  const rawPublicKey = opts.publicKey || opts;
  const publicKey = { ...rawPublicKey };

  if (typeof publicKey.challenge === "string") {
    publicKey.challenge = base64UrlToBuffer(publicKey.challenge);
  }

  if (Array.isArray(publicKey.allowCredentials)) {
    publicKey.allowCredentials = publicKey.allowCredentials.map((c: any) => ({
      ...c,
      id: typeof c.id === "string" ? base64UrlToBuffer(c.id) : c.id,
    }));
  }

  return { publicKey };
}

export function serializeRequestResponse(assertion: any): any {
  return {
    id: assertion.id,
    rawId: bufferToBase64Url(assertion.rawId),
    type: assertion.type,
    response: {
      clientDataJSON: bufferToBase64Url(assertion.response.clientDataJSON),
      authenticatorData: bufferToBase64Url(assertion.response.authenticatorData),
      signature: bufferToBase64Url(assertion.response.signature),
      userHandle: assertion.response.userHandle ? bufferToBase64Url(assertion.response.userHandle) : null,
    },
  };
}
