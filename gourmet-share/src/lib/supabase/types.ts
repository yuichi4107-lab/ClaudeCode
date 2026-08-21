export type Database = {
  public: {
    Tables: {
      profiles: {
        Row: {
          id: string;
          display_name: string;
          avatar_url: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id: string;
          display_name: string;
          avatar_url?: string | null;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          id?: string;
          display_name?: string;
          avatar_url?: string | null;
          updated_at?: string;
        };
        Relationships: [];
      };
      restaurants: {
        Row: {
          id: string;
          name: string;
          address: string | null;
          genre: string;
          price_range: string;
          url: string | null;
          latitude: number;
          longitude: number;
          registered_by: string;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          name: string;
          address?: string | null;
          genre: string;
          price_range: string;
          url?: string | null;
          latitude: number;
          longitude: number;
          registered_by: string;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          name?: string;
          address?: string | null;
          genre?: string;
          price_range?: string;
          url?: string | null;
          latitude?: number;
          longitude?: number;
          updated_at?: string;
        };
        Relationships: [];
      };
      reactions: {
        Row: {
          id: string;
          restaurant_id: string;
          user_id: string;
          reaction_type: string;
          created_at: string;
        };
        Insert: {
          id?: string;
          restaurant_id: string;
          user_id: string;
          reaction_type: string;
          created_at?: string;
        };
        Update: {
          restaurant_id?: string;
          user_id?: string;
          reaction_type?: string;
        };
        Relationships: [];
      };
    };
    Views: {
      restaurants_with_counts: {
        Row: {
          id: string;
          name: string;
          address: string | null;
          genre: string;
          price_range: string;
          url: string | null;
          latitude: number;
          longitude: number;
          registered_by: string;
          created_at: string;
          updated_at: string;
          registered_by_name: string;
          total_reactions: number;
          unique_reactors: number;
        };
        Relationships: [];
      };
    };
    Functions: {
      get_reaction_counts: {
        Args: { p_restaurant_id: string };
        Returns: { reaction_type: string; count: number }[];
      };
    };
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
};

export type Profile = Database['public']['Tables']['profiles']['Row'];
export type Restaurant = Database['public']['Tables']['restaurants']['Row'];
export type Reaction = Database['public']['Tables']['reactions']['Row'];

export type RestaurantWithCounts = Database['public']['Views']['restaurants_with_counts']['Row'] & {
  reaction_counts?: Record<string, number>;
};
