"""Builds model clients and fallback chains for each spec role from env vars and spec config."""

from __future__ import annotations 

import logging 
import os 
from enum import StrEnum 
from typing import Any 

from baps .core .run_config import RoleConfig ,RunConfig 
from baps .models .models import (
AnthropicClient ,
Backend ,
FallbackClient ,
ModelClient ,
OllamaClient ,
OpenAIClient ,
)

logger =logging .getLogger (__name__ )

_DEFAULT_OLLAMA_MODEL ="gemma4:e4b"
_DEFAULT_OLLAMA_BASE_URL ="http://localhost:11434"
_DEFAULT_ANTHROPIC_MODEL ="claude-sonnet-4-6"
_DEFAULT_ANTHROPIC_BASE_URL ="https://api.anthropic.com"
_DEFAULT_OPENAI_MODEL ="gpt-4o"
_DEFAULT_OPENAI_BASE_URL ="https://api.openai.com/v1"

VALID_BACKENDS =frozenset (Backend )


class SpecRole (StrEnum ):
    """Named roles used in spec-file configuration and role-specific client resolution."""
    BLUE ="blue"
    RED ="red"
    REFEREE ="referee"
    CREATE_GAME ="create_game"
    DECOMPOSE ="decompose"
    CREATE_GAME_RED ="create_game_red"
    SUMMARIZE ="summarize"


_VALID_SPEC_ROLES =frozenset (SpecRole )


def _build_client (backend :str |Backend ,model :str )->ModelClient :
    """Construct a model client for the given backend and model id."""
    if backend ==Backend .ANTHROPIC :
        api_key =os .getenv ("ANTHROPIC_API_KEY","")
        if not api_key .strip ():
            raise ValueError ("ANTHROPIC_API_KEY must be set when using anthropic backend")
        return AnthropicClient (
        model =model ,
        api_key =api_key ,
        base_url =os .getenv ("BAPS_ANTHROPIC_BASE_URL",_DEFAULT_ANTHROPIC_BASE_URL ),
        )
    if backend ==Backend .OPENAI :
        api_key =os .getenv ("OPENAI_API_KEY","")
        if not api_key .strip ():
            raise ValueError ("OPENAI_API_KEY must be set when using openai backend")
        return OpenAIClient (
        model =model ,
        api_key =api_key ,
        base_url =os .getenv ("BAPS_OPENAI_BASE_URL",_DEFAULT_OPENAI_BASE_URL ),
        )
    return OllamaClient (
    model =model ,
    base_url =os .getenv ("BAPS_OLLAMA_BASE_URL",_DEFAULT_OLLAMA_BASE_URL ),
    )


def _build_client_for_backend (backend :str |Backend )->ModelClient :
    """Build a client for the given backend using its default model env var."""
    if backend ==Backend .ANTHROPIC :
        return _build_client (backend ,os .getenv ("BAPS_ANTHROPIC_MODEL",_DEFAULT_ANTHROPIC_MODEL ))
    if backend ==Backend .OPENAI :
        return _build_client (backend ,os .getenv ("BAPS_OPENAI_MODEL",_DEFAULT_OPENAI_MODEL ))
    return _build_client (Backend .OLLAMA ,os .getenv ("BAPS_OLLAMA_MODEL",_DEFAULT_OLLAMA_MODEL ))


def _build_multi_backend_client ()->ModelClient |None :
    """Parse BAPS_BACKENDS and return a (Fallback)Client if set, else None."""
    backends_raw =os .getenv ("BAPS_BACKENDS","").strip ()
    if not backends_raw :
        return None 
    backends =[b .strip ().lower ()for b in backends_raw .split (",")if b .strip ()]
    if not backends :
        raise ValueError ("BAPS_BACKENDS must contain at least one backend")
    clients =[_build_client_for_backend (b )for b in backends ]
    return FallbackClient (clients )if len (clients )>1 else clients [0 ]


def _build_model_client ()->ModelClient :
    """Build the default model client from BAPS_BACKENDS or BAPS_BACKEND env vars."""
    client =_build_multi_backend_client ()
    if client is not None :
        return client 
    return _build_client_for_backend (os .getenv ("BAPS_BACKEND","ollama").lower ())


def _build_planner_model_client ()->ModelClient :
    """Build the planner (create_game) model client, preferring BAPS_OLLAMA_PLANNER_MODEL when set."""
    client =_build_multi_backend_client ()
    if client is not None :
        return client 
    backend =os .getenv ("BAPS_BACKEND","ollama").lower ()
    if backend ==Backend .ANTHROPIC :
        return _build_client (backend ,os .getenv ("BAPS_ANTHROPIC_MODEL",_DEFAULT_ANTHROPIC_MODEL ))
    if backend ==Backend .OPENAI :
        return _build_client (backend ,os .getenv ("BAPS_OPENAI_MODEL",_DEFAULT_OPENAI_MODEL ))
    model =(
    os .getenv ("BAPS_OLLAMA_PLANNER_MODEL")
    or os .getenv ("BAPS_OLLAMA_MODEL",_DEFAULT_OLLAMA_MODEL )
    )
    return _build_client (Backend .OLLAMA ,model )


def build_role_client (role :str )->ModelClient :
    """Build a model client for a named role (blue, red, referee, create_game).

    Checks BAPS_{ROLE}_BACKEND and BAPS_{ROLE}_MODEL first; falls back to the
    global _build_model_client() when no role-specific vars are set.
    """
    role_upper =role .upper ()
    role_backend =os .getenv (f"BAPS_{role_upper }_BACKEND","").strip ().lower ()
    role_model =os .getenv (f"BAPS_{role_upper }_MODEL","").strip ()

    if not role_backend and not role_model :
        return _build_model_client ()

    backend =role_backend or os .getenv ("BAPS_BACKEND","ollama").lower ()
    if backend ==Backend .ANTHROPIC :
        model =role_model or os .getenv ("BAPS_ANTHROPIC_MODEL",_DEFAULT_ANTHROPIC_MODEL )
    elif backend ==Backend .OPENAI :
        model =role_model or os .getenv ("BAPS_OPENAI_MODEL",_DEFAULT_OPENAI_MODEL )
    else :
        model =role_model or os .getenv ("BAPS_OLLAMA_MODEL",_DEFAULT_OLLAMA_MODEL )
    return _build_client (backend ,model )


def _build_decompose_client ()->ModelClient :
    """Build a model client for the decompose role.

    Checks BAPS_DECOMPOSE_BACKEND / BAPS_DECOMPOSE_MODEL first.
    Falls back to the create_game client when no decompose-specific vars are set,
    so the decompose role is a transparent no-op by default.
    """
    role_backend =os .getenv ("BAPS_DECOMPOSE_BACKEND","").strip ().lower ()
    role_model =os .getenv ("BAPS_DECOMPOSE_MODEL","").strip ()
    if role_backend or role_model :
        return build_role_client (SpecRole .DECOMPOSE )
    return _build_planner_model_client ()


def _parse_role_backend_model (cfg :dict ,path :str )->dict [str ,str ]:
    """Parse backend and model fields from a role config dict, validating backend."""
    parsed :dict [str ,str ]={}
    for field in ("backend","model"):
        if field in cfg :
            val =str (cfg [field ]).strip ()
            if field =="backend":
                val =val .lower ()
                if val not in VALID_BACKENDS :
                    raise ValueError (
                    f"spec '{path }.backend' must be one of "
                    f"{sorted (VALID_BACKENDS )}, got {val !r }"
                    )
            parsed [field ]=val 
    return parsed 


def _parse_role_config (cfg :dict ,path :str )->RoleConfig :
    """Parse a role config dict, recursively including arbitrarily deep fallback chains."""
    parsed :dict [str ,str |RoleConfig ]=_parse_role_backend_model (cfg ,path )
    if "fallback"in cfg :
        fallback_raw =cfg ["fallback"]
        if not isinstance (fallback_raw ,dict ):
            raise ValueError (f"spec '{path }.fallback' must be a mapping")
        parsed ["fallback"]=_parse_role_config (fallback_raw ,f"{path }.fallback")
    return RoleConfig (**parsed )


def parse_spec_roles (roles_raw :object )->dict [str ,RoleConfig ]:
    """Parse the raw roles mapping from a spec file into a validated dict of RoleConfig objects."""
    if not isinstance (roles_raw ,dict ):
        raise ValueError ("spec 'roles' must be a mapping")
    result :dict [str ,RoleConfig ]={}
    for role ,role_cfg in roles_raw .items ():
        if role not in _VALID_SPEC_ROLES :
            raise ValueError (
            f"Unknown role {role !r } in spec 'roles'. Valid roles: {sorted (_VALID_SPEC_ROLES )}"
            )
        if not isinstance (role_cfg ,dict ):
            raise ValueError (f"spec 'roles.{role }' must be a mapping")
        result [role ]=_parse_role_config (role_cfg ,f"roles.{role }")
    return result 


def resolve_backend_model (role :str ,config :RunConfig )->tuple [str ,str ]:
    """Resolve backend and model for a role.

    Precedence: role-spec > global-spec > role-env > global-env > error.
    Raises ValueError if nothing is configured.
    """
    spec_roles =config .spec_roles or {}
    role_cfg =spec_roles .get (role )
    role_upper =role .upper ()

    backend =(
    ((role_cfg .backend .value if role_cfg and role_cfg .backend else "")).strip ().lower ()
    or ((config .spec_backend .value if config .spec_backend else "")).strip ().lower ()
    or os .getenv (f"BAPS_{role_upper }_BACKEND","").strip ().lower ()
    or os .getenv ("BAPS_BACKEND","").strip ().lower ()
    )

    env_model :str =""
    if backend ==Backend .ANTHROPIC :
        env_model =os .getenv ("BAPS_ANTHROPIC_MODEL","").strip ()
    elif backend ==Backend .OPENAI :
        env_model =os .getenv ("BAPS_OPENAI_MODEL","").strip ()
    elif backend :
        env_model =os .getenv ("BAPS_OLLAMA_MODEL","").strip ()

    model =(
    ((role_cfg .model if role_cfg and role_cfg .model else "")).strip ()
    or (config .spec_model or "").strip ()
    or os .getenv (f"BAPS_{role_upper }_MODEL","").strip ()
    or env_model 
    )

    if not backend or not model :
        raise ValueError (
        "No model configured. Set backend and model in your spec file or via environment variables."
        )

    if backend not in VALID_BACKENDS :
        raise ValueError (
        f"Unknown backend {backend !r }. Valid options: {sorted (VALID_BACKENDS )}"
        )

    return backend ,model 


def build_client_for_role (role :str ,config :RunConfig )->ModelClient :
    """Build a model client for a role, applying spec > env precedence."""
    backend ,model =resolve_backend_model (role ,config )
    return _build_client (backend ,model )


def build_fallback_chain_for_role (role :str ,config :RunConfig )->list [tuple [str ,ModelClient ]]:
    """Build the ordered fallback chain for a role.

    Returns a list of (model_label, client) pairs from the spec's fallback chain,
    following arbitrarily deep fallback.fallback nesting. Returns [] when no fallback
    is configured.
    """
    spec_roles =config .spec_roles or {}
    role_cfg =spec_roles .get (role )
    chain :list [tuple [str ,ModelClient ]]=[]
    current =role_cfg .fallback if role_cfg is not None else None 
    while current is not None :
        backend =current .backend .value if current .backend else ""
        model =(current .model or "").strip ()
        if not backend or not model :
            break 
        chain .append ((model ,_build_client (backend ,model )))
        current =current .fallback 
    return chain 


def _build_fallback_client_for_role (role :str ,config :RunConfig )->ModelClient |None :
    """Return the first fallback client for a role, or None if no fallback is configured.

    Kept for backward compatibility. Use build_fallback_chain_for_role for full chain support.
    """
    chain =build_fallback_chain_for_role (role ,config )
    return chain [0 ][1 ]if chain else None 


def make_fallback_chain_fn (
role_name :str ,
primary_model :str ,
chain :list [tuple [str ,ModelClient ]],
)->Any :
    """Build a fallback callable that tries each client in the chain in order.

    Logs a WARNING before escalating to each subsequent model. Raises RuntimeError
    when the entire chain is exhausted. Returns None when chain is empty.
    """
    if not chain :
        return None 
    from baps .models .model_output import wrap_json_prompt 

    def fn (prompt :str )->str :
        prev =primary_model 
        for model_label ,client in chain :
            logger .warning (
            "%s: model %s exhausted retries, escalating to %s",
            role_name ,prev ,model_label ,
            )
            try :
                return client .generate (wrap_json_prompt (prompt ))
            except Exception as exc :# noqa: BLE001
                logger .warning ("%s: fallback model %s failed: %s",role_name ,model_label ,exc )
                prev =model_label 
        raise RuntimeError (f"{role_name }: all models in fallback chain exhausted")

    return fn 


def _make_fallback_fn (client :ModelClient )->Any :
    """Build a fallback generate callable that wraps the correction prompt with JSON-only instruction."""
    from baps .models .model_output import wrap_json_prompt 
    def fn (prompt :str )->str :
        return client .generate (wrap_json_prompt (prompt ))
    return fn 
