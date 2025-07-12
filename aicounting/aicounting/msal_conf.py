
import os

import jwt
import requests

import msal
import os


class MsalConf:

    TENANT_ID = os.environ.get('AZURE_TENANT_ID')
    CLIENT_ID = os.environ.get('AZURE_CLIENT_ID')
    CLIENT_SECRET = os.environ.get('AZURE_CLIENT_SECRET')

    AUTHORITY= f"https://login.microsoftonline.com/{TENANT_ID}"
    APP_URI= f"https://OnestoneB2C.onmicrosoft.com/{CLIENT_ID}"
    
    JWKS_URI= f"{AUTHORITY}/discovery/v2.0/keys"

    SCOPE = ["User.Read"]
    
    MSAL_APP = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )

    REDIRECT_URI = "https://b7001b19d7b2.ngrok-free.app/api/v1/auth/callback"
        
    def get_public_key(self, jwt_token):
        public_key = ""
        
        jwks_response = requests.get(self.JWKS_URI)
        jwks = jwks_response.json()
        # Find the appropriate key from the JWKS based on the token's "kid" (Key ID) claim
        header = jwt.get_unverified_header(jwt_token)
        kid = header['kid']

        # Find the key with a matching "kid" in the JWKS
        for key in jwks['keys']:
            if key['kid'] == kid:
                # Use the found key for verification
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break
        else:
            # Handle the case where a matching key was not found
            raise ValueError("Matching key not found in JWKS")
        
        return public_key, self.APP_URI
