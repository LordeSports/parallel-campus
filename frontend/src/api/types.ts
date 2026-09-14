/**
 * 本文件由 `backend/scripts/gen_ts_types.py` 从 `backend/openapi.json` 生成。
 * 等价于 `npx openapi-typescript http://localhost:8000/api/openapi.json -o src/api/types.ts`。
 * 请勿手改；后端契约变更后重新生成。
 */

/* eslint-disable */

export type ActiveEventView = {
  "id": string;
  "kind": string;
  "title": string;
  "description"?: string;
  "location_id"?: string | null;
  "start_tick"?: number;
  "end_tick"?: number;
  "tags"?: string[];
  "source_title"?: string | null;
  "source_url"?: string | null;
  "status"?: string;
};

export type AdminLoginRequest = {
  "username": string;
  "password": string;
};

export type AdminOverviewView = {
  "world": WorldStateView;
  "status": AdminStatusView;
  "control_mode": string;
  "counts": Record<string, number>;
  "usage_by_model": UsageGroupView[];
  "recent_usage": UsageItemView[];
  "scenes": ActiveEventView[];
};

export type AdminSessionView = {
  "enabled": boolean;
  "authenticated": boolean;
  "username"?: string | null;
};

export type AdminStatusView = {
  "mode": string;
  "remaining_ticks"?: number;
  "tick"?: number;
  "llm_today"?: LlmTodayView;
  "zhihu_today"?: ZhihuTodayView;
};

export type AdminWeatherRequest = {
  "kind": "sunny" | "cloudy" | "rainy" | "foggy" | "windy";
  "temp_c": number;
  "text"?: string;
};

export type ApiSettingsRequest = {
  "llm_base_url": string;
  "llm_model_strong": string;
  "llm_model_cheap": string;
  "llm_enabled"?: boolean;
  "llm_api_key"?: string | null;
  "zhihu_access_secret"?: string | null;
  "zhihu_oauth_app_id"?: string;
  "zhihu_oauth_app_key"?: string | null;
  "clear_llm_api_key"?: boolean;
  "clear_zhihu_access_secret"?: boolean;
  "clear_zhihu_oauth_app_key"?: boolean;
};

export type ApiSettingsView = {
  "llm_base_url": string;
  "llm_model_strong": string;
  "llm_model_cheap": string;
  "llm_enabled"?: boolean;
  "llm_api_key_configured": boolean;
  "zhihu_access_secret_configured": boolean;
  "zhihu_oauth_app_id": string;
  "zhihu_oauth_app_key_configured": boolean;
  "dev_mode": boolean;
  "tick_seconds_online": number;
  "tick_seconds_idle": number;
};

export type AuthorView = {
  "id": string;
  "name": string;
  "avatar_key": string;
  "kind": "player" | "npc" | "system";
};

export type AvatarView = {
  "id": string;
  "kind": "player" | "npc" | "system";
  "name": string;
  "avatar_key": string;
  "location_id": string;
  "activity"?: string;
  "mood"?: MoodView;
  "is_asleep"?: boolean;
  "is_me"?: boolean;
  "dialogue_id"?: string | null;
  "energy"?: number;
  "identity"?: IdentityView;
  "appearance"?: string;
  "archetype"?: string;
  "summary"?: string;
  "recent_memories"?: MemoryItemView[];
  "top_relationships"?: RelationshipItemView[];
  "whispers_left_today"?: number;
  "deployed_at_tick"?: number;
  "persona_version"?: number;
};

export type BriefingView = {
  "day": number;
  "text": string;
};

export type CampusIdentity = {
  "major"?: string;
  "grade"?: "大一" | "大二" | "大三" | "大四" | "研一" | "研二" | "研三";
  "club"?: string | null;
};

export type CampusMapView = {
  "version": number;
  "cols": number;
  "rows": number;
  "title"?: string;
  "updated_at"?: string | null;
  "updated_by"?: string | null;
  "objects"?: MapObjectView[];
};

export type CharacterDetailView = {
  "id": string;
  "kind": "player" | "npc" | "system";
  "name": string;
  "avatar_key": string;
  "location_id": string;
  "activity"?: string;
  "mood"?: MoodView;
  "is_asleep"?: boolean;
  "is_me"?: boolean;
  "dialogue_id"?: string | null;
  "energy"?: number;
  "identity"?: IdentityView;
  "appearance"?: string;
  "archetype"?: string;
  "summary"?: string;
  "recent_memories"?: MemoryItemView[];
  "top_relationships"?: RelationshipItemView[];
};

export type CharacterSummaryView = {
  "id": string;
  "kind": "player" | "npc" | "system";
  "name": string;
  "avatar_key": string;
  "location_id": string;
  "activity"?: string;
  "mood"?: MoodView;
  "is_asleep"?: boolean;
  "is_me"?: boolean;
  "dialogue_id"?: string | null;
  "energy"?: number;
};

export type ClockRequest = {
  "day": number;
  "minute_of_day": number;
};

export type CommentView = {
  "id": string;
  "post_id": string;
  "author"?: AuthorView | null;
  "author_label"?: string | null;
  "text": string;
  "tick": number;
  "time_label"?: string;
};

export type CreateCommentRequest = {
  "text": string;
};

export type CreatePostRequest = {
  "board"?: "tree_hole";
  "text": string;
};

export type DeployRequest = {
  "display_name": string;
  "avatar_key"?: string;
  "appearance"?: string;
  "major"?: string;
  "grade"?: "大一" | "大二" | "大三" | "大四" | "研一" | "研二" | "研三";
  "club"?: string | null;
};

export type DevLoginRequest = {
  "name"?: string;
};

export type DialogueTurnView = {
  "speaker_id": string;
  "text": string;
};

export type DialogueView = {
  "id": string;
  "tick": number;
  "time_label": string;
  "location_id": string;
  "a_id": string;
  "b_id": string;
  "turns"?: DialogueTurnView[];
  "a_to_b_delta"?: number;
  "b_to_a_delta"?: number;
  "ended_because"?: string;
  "is_player_involved"?: boolean;
};

export type DiaryEntryView = {
  "tick": number;
  "time_label"?: string;
  "type": string;
  "text": string;
  "payload"?: Record<string, unknown>;
};

export type DiaryView = {
  "day": number;
  "entries"?: DiaryEntryView[];
  "mood_series"?: MoodPointView[];
  "reflections"?: ReflectionItemView[];
  "whispers"?: WhisperItemView[];
};

export type EventView = {
  "id": string;
  "tick": number;
  "day": number;
  "type": string;
  "actor_id"?: string | null;
  "target_id"?: string | null;
  "location_id"?: string | null;
  "payload"?: Record<string, unknown>;
  "time_label"?: string;
};

export type FastForwardResponse = {
  "mode": string;
  "remaining_ticks": number;
};

export type HTTPValidationError = {
  "detail"?: ValidationError[];
};

export type HealthView = {
  "status"?: string;
  "version"?: string;
  "tick"?: number;
  "mode"?: string;
  "dev_mode"?: boolean;
};

export type HotPullResponse = {
  "events_created": number;
};

export type IdentityView = {
  "major"?: string;
  "grade"?: string;
  "club"?: string | null;
};

export type Interest = {
  "topic": string;
  "weight": number;
  "evidence"?: string[];
};

export type LikeResponse = {
  "liked": boolean;
  "like_count": number;
};

export type LlmTodayView = {
  "calls"?: number;
  "prompt_tokens"?: number;
  "completion_tokens"?: number;
  "fail_streak"?: number;
};

export type LocationView = {
  "id": string;
  "name": string;
  "emoji": string;
  "x": number;
  "y": number;
  "w": number;
  "h": number;
  "outdoor": boolean;
  "description": string;
  "affordances"?: string[];
  "ambience"?: Record<string, string>;
  "capacity": number;
  "occupants"?: string[];
};

export type MapObjectInput = {
  "id"?: string | null;
  "kind": "ground" | "building" | "prop";
  "variant": string;
  "tx": number;
  "ty": number;
  "tw"?: number;
  "th"?: number;
  "height"?: number;
  "layer"?: number;
  "name"?: string;
  "location_id"?: string | null;
  "props"?: Record<string, unknown>;
};

export type MapObjectView = {
  "id": string;
  "kind": "ground" | "building" | "prop";
  "variant": string;
  "tx": number;
  "ty": number;
  "tw": number;
  "th": number;
  "height"?: number;
  "layer"?: number;
  "name"?: string;
  "location_id"?: string | null;
  "props"?: Record<string, unknown>;
};

export type MapSaveRequest = {
  "objects"?: MapObjectInput[];
  "title"?: string | null;
};

export type MemoryItemView = {
  "tick": number;
  "kind": string;
  "text": string;
  "importance"?: number;
};

export type ModeResponse = {
  "mode": string;
};

export type MoodPointView = {
  "tick": number;
  "valence": number;
  "arousal": number;
};

export type MoodView = {
  "valence"?: number;
  "arousal"?: number;
};

export type NpcRequest = {
  "name": string;
  "avatar_key"?: string;
  "persona": PersonaFile;
  "location_id"?: string;
  "activity"?: string;
  "energy"?: number;
  "mood_valence"?: number;
  "mood_arousal"?: number;
  "is_asleep"?: boolean;
  "is_active"?: boolean;
};

export type NpcView = {
  "id": string;
  "kind": "player" | "npc" | "system";
  "name": string;
  "avatar_key": string;
  "location_id": string;
  "activity"?: string;
  "mood"?: MoodView;
  "is_asleep"?: boolean;
  "is_me"?: boolean;
  "dialogue_id"?: string | null;
  "energy"?: number;
  "is_active": boolean;
  "persona": PersonaFile;
};

export type PersonaFile = {
  "display_name": string;
  "archetype": string;
  "mbti_like": Record<string, number>;
  "big_five": Record<string, number>;
  "interests": Interest[];
  "stances"?: Stance[];
  "speaking_style"?: SpeakingStyle;
  "values"?: string[];
  "social"?: Social;
  "campus_identity"?: CampusIdentity;
  "appearance"?: string;
  "summary": string;
};

export type PersonaResponse = {
  "file": PersonaFile;
  "thin"?: boolean;
  "version"?: number;
  "source_stats"?: SourceStats;
  "confirmed_at"?: string | null;
  "generated_left_today"?: number;
};

export type PersonaUpdateRequest = {
  "file": PersonaFile;
};

export type PostDetailView = {
  "post": PostView;
  "comments"?: CommentView[];
};

export type PostView = {
  "id": string;
  "board": "wall" | "tree_hole" | "notice";
  "author"?: AuthorView | null;
  "author_label"?: string | null;
  "text": string;
  "tick": number;
  "time_label"?: string;
  "like_count"?: number;
  "comment_count"?: number;
  "source"?: SourceView | null;
  "event_id"?: string | null;
  "liked_by_me"?: boolean;
};

export type ReflectionItemView = {
  "tick": number;
  "text": string;
  "importance"?: number;
};

export type RelationshipItemView = {
  "character_id": string;
  "name": string;
  "affinity": number;
  "tags"?: string[];
};

export type ReportFriendCharacter = {
  "id": string;
  "name": string;
  "avatar_key": string;
  "kind": "player" | "npc" | "system";
  "archetype"?: string;
};

export type ReportFriendView = {
  "character": ReportFriendCharacter;
  "story": string;
  "shared_topics"?: string[];
  "affinity": number;
  "affinity_delta": number;
  "is_human"?: boolean;
  "zhihu_url"?: string | null;
};

export type ReportView = {
  "day": number;
  "generated_tick": number;
  "summary": string;
  "top_friends"?: ReportFriendView[];
};

export type SceneRequest = {
  "title": string;
  "description"?: string;
  "location_id": string;
  "duration_ticks"?: number;
  "tags"?: string[];
};

export type SimulationRequest = {
  "mode": "auto" | "paused" | "idle" | "online" | "fast_forward";
  "tick_seconds_online"?: number;
  "tick_seconds_idle"?: number;
  "ticks"?: number;
};

export type Social = {
  "initiative"?: number;
  "group_pref"?: "独处" | "小圈子" | "广交";
  "avoid_topics"?: string[];
};

export type SourceStats = {
  "contents"?: number;
  "followees"?: number;
  "favlists"?: number;
  "saved_items"?: number;
  "failed"?: string[];
};

export type SourceView = {
  "title": string;
  "url": string;
};

export type SpeakingStyle = {
  "tone"?: string;
  "emoji"?: boolean;
  "length"?: "短" | "中" | "长";
  "catchphrases"?: string[];
};

export type Stance = {
  "text": string;
  "evidence"?: string[];
};

export type UsageGroupView = {
  "model": string;
  "calls": number;
  "prompt_tokens": number;
  "completion_tokens": number;
};

export type UsageItemView = {
  "id": string;
  "at": string;
  "model": string;
  "tier": string;
  "template": string;
  "prompt_tokens": number;
  "completion_tokens": number;
  "latency_ms": number;
  "ok": boolean;
};

export type User = {
  "id": string;
  "display_name": string;
  "avatar_key"?: string;
  "auth_kind"?: string;
  "zhihu_uid"?: string | null;
  "zhihu_url_token"?: string | null;
  "zhihu_token_enc"?: string | null;
  "token_expires_at"?: string | null;
  "created_at"?: string;
  "last_login_at"?: string;
};

export type UserView = {
  "id": string;
  "display_name": string;
  "avatar_key": string;
  "auth_kind": "zhihu" | "dev";
  "has_persona"?: boolean;
  "character_id"?: string | null;
  "zhihu_url"?: string | null;
};

export type ValidationError = {
  "loc": (string | number)[];
  "msg": string;
  "type": string;
  "input"?: unknown;
  "ctx"?: Record<string, unknown>;
};

export type WeatherView = {
  "kind"?: "sunny" | "cloudy" | "rainy" | "foggy" | "windy";
  "temp_c"?: number;
  "text"?: string;
};

export type WhisperItemView = {
  "id": string;
  "text": string;
  "tick": number;
  "accepted"?: boolean | null;
  "reason"?: string | null;
};

export type WhisperRequest = {
  "text": string;
};

export type WhisperResponseView = {
  "whisper_id": string;
  "whispers_left_today": number;
};

export type WorldStateView = {
  "day": number;
  "minute_of_day": number;
  "weekday": number;
  "tick": number;
  "time_label": string;
  "weather": WeatherView;
  "speed_mode": string;
  "tick_seconds": number;
  "observers"?: number;
  "degraded"?: boolean;
  "active_events"?: ActiveEventView[];
  "briefing"?: BriefingView | null;
};

export type ZhihuTodayView = {
  "hot_list"?: number;
  "zhihu_search"?: number;
  "zhida"?: number;
  "user_data"?: number;
};

export interface paths {
  "/api/admin/clock": {
    put: "clock_api_admin_clock_put";
  };
  "/api/admin/comments/{comment_id}": {
    delete: "delete_comment_api_admin_comments__comment_id__delete";
  };
  "/api/admin/fast-forward": {
    post: "fast_forward_api_admin_fast_forward_post";
  };
  "/api/admin/hot-pull": {
    post: "hot_pull_api_admin_hot_pull_post";
  };
  "/api/admin/locations": {
    get: "locations_api_admin_locations_get";
  };
  "/api/admin/login": {
    post: "admin_login_api_admin_login_post";
  };
  "/api/admin/logout": {
    post: "admin_logout_api_admin_logout_post";
  };
  "/api/admin/map": {
    get: "get_campus_map_api_admin_map_get";
    put: "save_campus_map_api_admin_map_put";
  };
  "/api/admin/npcs": {
    get: "npcs_api_admin_npcs_get";
    post: "create_npc_api_admin_npcs_post";
  };
  "/api/admin/npcs/{character_id}": {
    put: "update_npc_api_admin_npcs__character_id__put";
  };
  "/api/admin/overview": {
    get: "overview_api_admin_overview_get";
  };
  "/api/admin/pause": {
    post: "pause_api_admin_pause_post";
  };
  "/api/admin/posts/{post_id}": {
    delete: "delete_post_api_admin_posts__post_id__delete";
  };
  "/api/admin/reseed": {
    post: "reseed_api_admin_reseed_post";
  };
  "/api/admin/resume": {
    post: "resume_api_admin_resume_post";
  };
  "/api/admin/scenes": {
    get: "scenes_api_admin_scenes_get";
    post: "create_scene_api_admin_scenes_post";
  };
  "/api/admin/scenes/{scene_id}/end": {
    post: "end_scene_api_admin_scenes__scene_id__end_post";
  };
  "/api/admin/session": {
    get: "admin_session_api_admin_session_get";
  };
  "/api/admin/settings": {
    get: "get_api_settings_api_admin_settings_get";
    put: "set_api_settings_api_admin_settings_put";
  };
  "/api/admin/simulation": {
    put: "simulation_api_admin_simulation_put";
  };
  "/api/admin/status": {
    get: "status_api_admin_status_get";
  };
  "/api/admin/weather": {
    put: "weather_api_admin_weather_put";
  };
  "/api/auth/dev-login": {
    post: "dev_login_api_auth_dev_login_post";
  };
  "/api/auth/logout": {
    post: "logout_api_auth_logout_post";
  };
  "/api/auth/me": {
    delete: "delete_me_api_auth_me_delete";
    get: "me_api_auth_me_get";
  };
  "/api/auth/oauth-log": {
    get: "oauth_debug_log_api_auth_oauth_log_get";
  };
  "/api/auth/zhihu/callback": {
    get: "zhihu_callback_api_auth_zhihu_callback_get";
  };
  "/api/auth/zhihu/login": {
    get: "zhihu_login_api_auth_zhihu_login_get";
  };
  "/api/avatar": {
    get: "get_avatar_api_avatar_get";
  };
  "/api/avatar/diary": {
    get: "get_diary_api_avatar_diary_get";
  };
  "/api/avatar/report": {
    get: "get_report_api_avatar_report_get";
  };
  "/api/avatar/whisper": {
    post: "send_whisper_api_avatar_whisper_post";
  };
  "/api/health": {
    get: "health_api_health_get";
  };
  "/api/persona": {
    get: "get_persona_api_persona_get";
    put: "put_persona_api_persona_put";
  };
  "/api/persona/deploy": {
    post: "deploy_api_persona_deploy_post";
  };
  "/api/persona/generate": {
    post: "generate_api_persona_generate_post";
  };
  "/api/stream": {
    get: "stream_api_stream_get";
  };
  "/api/wall/posts": {
    get: "list_posts_api_wall_posts_get";
    post: "create_post_api_wall_posts_post";
  };
  "/api/wall/posts/{post_id}": {
    get: "get_post_api_wall_posts__post_id__get";
  };
  "/api/wall/posts/{post_id}/comments": {
    post: "create_comment_api_wall_posts__post_id__comments_post";
  };
  "/api/wall/posts/{post_id}/like": {
    post: "toggle_like_api_wall_posts__post_id__like_post";
  };
  "/api/world/characters": {
    get: "world_characters_api_world_characters_get";
  };
  "/api/world/characters/{character_id}": {
    get: "world_character_detail_api_world_characters__character_id__get";
  };
  "/api/world/dialogues/{dialogue_id}": {
    get: "world_dialogue_api_world_dialogues__dialogue_id__get";
  };
  "/api/world/events": {
    get: "world_events_api_world_events_get";
  };
  "/api/world/locations": {
    get: "world_locations_api_world_locations_get";
  };
  "/api/world/map": {
    get: "world_map_api_world_map_get";
  };
  "/api/world/state": {
    get: "world_state_api_world_state_get";
  };
}
