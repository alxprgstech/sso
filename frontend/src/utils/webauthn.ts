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

type EncodedDescriptor = Omit<PublicKeyCredentialDescriptor, "id"> & { id: string | BufferSource };
type EncodedUser = Omit<PublicKeyCredentialUserEntity, "id"> & { id: string | BufferSource };
export type EncodedCreationOptions = Omit<PublicKeyCredentialCreationOptions, "challenge" | "user" | "excludeCredentials"> & {
  challenge: string | BufferSource;
  user: EncodedUser;
  excludeCredentials?: EncodedDescriptor[];
};
export type EncodedRequestOptions = Omit<PublicKeyCredentialRequestOptions, "challenge" | "allowCredentials"> & {
  challenge: string | BufferSource;
  allowCredentials?: EncodedDescriptor[];
};

function unwrap<T>(options: string | T | { publicKey: T }): T {
  const parsed: T | { publicKey: T } = typeof options === "string" ? JSON.parse(options) : options;
  return "publicKey" in (parsed as { publicKey?: T })
    ? (parsed as { publicKey: T }).publicKey
    : parsed as T;
}

export function prepareCreationOptions(serverOptions: string | EncodedCreationOptions | { publicKey: EncodedCreationOptions }): CredentialCreationOptions {
  const raw = unwrap(serverOptions);
  return {
    publicKey: {
      ...raw,
      challenge: typeof raw.challenge === "string" ? base64UrlToBuffer(raw.challenge) : raw.challenge,
      user: { ...raw.user, id: typeof raw.user.id === "string" ? base64UrlToBuffer(raw.user.id) : raw.user.id },
      excludeCredentials: raw.excludeCredentials?.map((credential) => ({
        ...credential,
        id: typeof credential.id === "string" ? base64UrlToBuffer(credential.id) : credential.id,
      })),
    },
  };
}

export function serializeCreationResponse(cred: Credential): object {
  const publicKey = cred as PublicKeyCredential;
  const attestation = publicKey.response as AuthenticatorAttestationResponse;
  const response: { clientDataJSON: string; attestationObject: string; transports?: string[] } = {
    clientDataJSON: bufferToBase64Url(attestation.clientDataJSON),
    attestationObject: bufferToBase64Url(attestation.attestationObject),
  };
  if (typeof attestation.getTransports === "function") {
    response.transports = attestation.getTransports();
  }
  return { id: publicKey.id, rawId: bufferToBase64Url(publicKey.rawId), type: publicKey.type, response };
}

export function prepareRequestOptions(serverOptions: string | EncodedRequestOptions | { publicKey: EncodedRequestOptions }): CredentialRequestOptions {
  const raw = unwrap(serverOptions);
  return {
    publicKey: {
      ...raw,
      challenge: typeof raw.challenge === "string" ? base64UrlToBuffer(raw.challenge) : raw.challenge,
      allowCredentials: raw.allowCredentials?.map((credential) => ({
        ...credential,
        id: typeof credential.id === "string" ? base64UrlToBuffer(credential.id) : credential.id,
      })),
    },
  };
}

export function serializeRequestResponse(assertion: Credential): object {
  const publicKey = assertion as PublicKeyCredential;
  const auth = publicKey.response as AuthenticatorAssertionResponse;
  return {
    id: publicKey.id,
    rawId: bufferToBase64Url(publicKey.rawId),
    type: publicKey.type,
    response: {
      clientDataJSON: bufferToBase64Url(auth.clientDataJSON),
      authenticatorData: bufferToBase64Url(auth.authenticatorData),
      signature: bufferToBase64Url(auth.signature),
      userHandle: auth.userHandle ? bufferToBase64Url(auth.userHandle) : null,
    },
  };
}
