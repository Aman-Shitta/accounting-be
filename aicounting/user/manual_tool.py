
import time
from openai import OpenAI


class ToolResourcesCodeInterpreter():

    """Base OpenAI Client."""
    def __init__(self, project_id="", api_key="", model="gpt-4o"):
        self.client = OpenAI(
            api_key=api_key,
            project=project_id
        )
        self.model = model
    
    def list_all_assistants(self):
        """List all assistants with their details including last used time"""
        try:
            assistants = self.client.beta.assistants.list(limit=100)
            
            print("\n" + "=" * 80)
            print("OPENAI ASSISTANTS LIST")
            print("=" * 80)
            
            if not assistants.data:
                print("No assistants found.")
                return []
            
            assistant_list = []
            for idx, assistant in enumerate(assistants.data, 1):
                created_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(assistant.created_at))
                
                # Get vector store IDs if available
                vector_store_ids = []
                if assistant.tool_resources and assistant.tool_resources.file_search:
                    vector_store_ids = assistant.tool_resources.file_search.vector_store_ids or []
                
                assistant_info = {
                    'id': assistant.id,
                    'name': assistant.name,
                    'model': assistant.model,
                    'created_at': created_at,
                    'vector_store_ids': vector_store_ids,
                    'tools': [tool.type for tool in assistant.tools] if assistant.tools else [],
                    'description': assistant.description
                }
                assistant_list.append(assistant_info)
                
                print(f"\n{idx}. Assistant ID: {assistant.id}")
                print(f"   Name: {assistant.name}")
                print(f"   Model: {assistant.model}")
                print(f"   Created At: {created_at}")
                print(f"   Description: {assistant.description or 'N/A'}")
                print(f"   Tools: {', '.join(assistant_info['tools']) or 'None'}")
                print(f"   Vector Store IDs: {', '.join(vector_store_ids) or 'None'}")
                print("-" * 40)
            
            print(f"\nTotal Assistants: {len(assistant_list)}")
            print("=" * 80)
            
            return assistant_list
            
        except Exception as e:
            print(f"Error listing assistants: {e}")
            print(f"Error listing assistants: {e}")
            return []

    def get_assistant_details(self, assistant_id):
        """Get detailed information about a specific assistant"""
        try:
            assistant = self.client.beta.assistants.retrieve(assistant_id=assistant_id)
            
            created_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(assistant.created_at))
            
            # Get vector store IDs
            vector_store_ids = []
            if assistant.tool_resources and assistant.tool_resources.file_search:
                vector_store_ids = assistant.tool_resources.file_search.vector_store_ids or []
            
            details = {
                'id': assistant.id,
                'name': assistant.name,
                'model': assistant.model,
                'created_at': created_at,
                'description': assistant.description,
                'instructions': assistant.instructions[:200] + '...' if assistant.instructions and len(assistant.instructions) > 200 else assistant.instructions,
                'tools': [tool.type for tool in assistant.tools] if assistant.tools else [],
                'vector_store_ids': vector_store_ids,
                'response_format': assistant.response_format,
                'temperature': assistant.temperature,
                'top_p': assistant.top_p,
            }
            
            return details
            
        except Exception as e:
            print(f"Error getting assistant details: {e}")
            return None

    def delete_vector_store(self, vector_store_id):
        """Delete a vector store and all its files"""
        try:
            # First, list and delete all files in the vector store
            try:
                files = self.client.vector_stores.files.list(vector_store_id=vector_store_id)
                for file in files.data:
                    try:
                        self.client.vector_stores.files.delete(
                            vector_store_id=vector_store_id,
                            file_id=file.id
                        )
                        print(f"   Deleted file {file.id} from vector store")
                    except Exception as e:
                        print(f"Error deleting file {file.id}: {e}")
            except Exception as e:
                print(f"Error listing vector store files: {e}")
            
            # Delete the vector store
            self.client.vector_stores.delete(vector_store_id=vector_store_id)
            print(f"   Deleted vector store: {vector_store_id}")
            return True
            
        except Exception as e:
            print(f"Error deleting vector store {vector_store_id}: {e}")
            return False

    def delete_assistant(self, assistant_id):
        """Delete an assistant and all its associated resources (vector stores, files)"""
        try:
            # Get assistant details first
            details = self.get_assistant_details(assistant_id)
            
            if not details:
                print(f"Assistant {assistant_id} not found.")
                return False
            
            print("\n" + "=" * 60)
            print("ASSISTANT TO BE DELETED")
            print("=" * 60)
            print(f"ID: {details['id']}")
            print(f"Name: {details['name']}")
            print(f"Model: {details['model']}")
            print(f"Created At: {details['created_at']}")
            print(f"Description: {details['description'] or 'N/A'}")
            print(f"Tools: {', '.join(details['tools']) or 'None'}")
            print(f"Vector Store IDs: {', '.join(details['vector_store_ids']) or 'None'}")
            print("=" * 60)
            
            # Delete vector stores associated with the assistant
            if details['vector_store_ids']:
                print("\nDeleting associated vector stores...")
                for vs_id in details['vector_store_ids']:
                    self.delete_vector_store(vs_id)
            
            # Delete the assistant
            self.client.beta.assistants.delete(assistant_id=assistant_id)
            print(f"\nSuccessfully deleted assistant: {assistant_id}")
            
            # Also delete from database if exists
            try:
                DimAICAssistant.objects.filter(assistant_id=assistant_id).delete()
                print("Removed assistant record from database.")
            except Exception as e:
                print(f"Error removing from database: {e}")
            
            return True
            
        except Exception as e:
            print(f"Error deleting assistant {assistant_id}: {e}")
            print(f"Error deleting assistant: {e}")
            return False

    def interactive_assistant_manager(self):
        """Interactive command-line tool for managing assistants"""
        print("\n" + "=" * 60)
        print("OPENAI ASSISTANT MANAGER")
        print("=" * 60)
        
        while True:
            print("\nOptions:")
            print("1. List all assistants")
            print("2. Get assistant details")
            print("3. Delete an assistant")
            print("4. List all vector stores")
            print("5. Delete a vector store")
            print("6. Exit")
            
            choice = input("\nEnter your choice (1-6): ").strip()
            
            if choice == '1':
                self.list_all_assistants()
                
            elif choice == '2':
                assistant_id = input("Enter assistant ID: ").strip()
                if assistant_id:
                    details = self.get_assistant_details(assistant_id)
                    if details:
                        print("\n" + "-" * 40)
                        for key, value in details.items():
                            print(f"{key}: {value}")
                        print("-" * 40)
                    else:
                        print("Assistant not found.")
                        
            elif choice == '3':
                assistant_id = input("Enter assistant ID to delete: ").strip()
                if assistant_id:
                    details = self.get_assistant_details(assistant_id)
                    if details:
                        print(f"\nYou are about to delete: {details['name']} ({assistant_id})")
                        confirm = input("Are you sure? (yes/no): ").strip().lower()
                        if confirm == 'yes':
                            self.delete_assistant(assistant_id)
                        else:
                            print("Deletion cancelled.")
                    else:
                        print("Assistant not found.")
                        
            elif choice == '4':
                self.list_all_vector_stores()
                
            elif choice == '5':
                vs_id = input("Enter vector store ID to delete: ").strip()
                if vs_id:
                    confirm = input(f"Are you sure you want to delete vector store {vs_id}? (yes/no): ").strip().lower()
                    if confirm == 'yes':
                        self.delete_vector_store(vs_id)
                    else:
                        print("Deletion cancelled.")
                        
            elif choice == '6':
                print("Exiting...")
                break
            else:
                print("Invalid choice. Please try again.")

    def list_all_vector_stores(self):
        """List all vector stores with their details"""
        try:
            vector_stores = self.client.vector_stores.list(limit=100)
            
            print("\n" + "=" * 80)
            print("VECTOR STORES LIST")
            print("=" * 80)
            
            if not vector_stores.data:
                print("No vector stores found.")
                return []
            
            vs_list = []
            for idx, vs in enumerate(vector_stores.data, 1):
                created_at = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(vs.created_at))
                last_active = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(vs.last_active_at)) if vs.last_active_at else 'Never'
                
                vs_info = {
                    'id': vs.id,
                    'name': vs.name,
                    'created_at': created_at,
                    'last_active_at': last_active,
                    'file_count': vs.file_counts.total if vs.file_counts else 0,
                    'status': vs.status
                }
                vs_list.append(vs_info)
                
                print(f"\n{idx}. Vector Store ID: {vs.id}")
                print(f"   Name: {vs.name}")
                print(f"   Created At: {created_at}")
                print(f"   Last Active: {last_active}")
                print(f"   File Count: {vs_info['file_count']}")
                print(f"   Status: {vs.status}")
                print("-" * 40)
            
            print(f"\nTotal Vector Stores: {len(vs_list)}")
            print("=" * 80)
            
            return vs_list
            
        except Exception as e:
            print(f"Error listing vector stores: {e}")
            print(f"Error listing vector stores: {e}")
            return []

    def cleanup_all_assistants(self, confirm=False):
        """Delete all assistants and their resources - USE WITH CAUTION"""
        if not confirm:
            print("WARNING: This will delete ALL assistants and their resources!")
            user_confirm = input("Type 'DELETE ALL' to confirm: ").strip()
            if user_confirm != 'DELETE ALL':
                print("Cleanup cancelled.")
                return False
        
        assistants = self.list_all_assistants()
        
        for assistant in assistants:
            print(f"\nDeleting {assistant['name']}...")
            self.delete_assistant(assistant['id'])
        
        print("\nCleanup complete.")
        return True


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    api_key = os.getenv('OPENAI_API_KEY')
    proj = os.getenv('OPENAI_PROJECT_ID')
    
    if not api_key:
        print("Error: OPENAI_API_KEY not found in environment variables")
    else:
        assistant_manager = ToolResourcesCodeInterpreter(project_id=proj, api_key=api_key)
        # assistant_manager.interactive_assistant_manager()

        lst = ["asst_91LWdf7VemiKl1EIz3mwXncL", "asst_tVpFl98bQyEbqMTO8GExnyl4", "asst_aVTQt0mMTErujHh2ScEsHbLV", "asst_fExM3UGrg6fVflhh01rRwwuy", "asst_F8Wsm6WXRrF4v9pqVgg7jRau", "asst_fX5ylDNwESfadQAx6yoXSW6U", "asst_Mg3uGgRYO424H1i6tkah4zD9", "asst_xEYzD8HMxl4XPEKzNaigOkQG", "asst_h2Ev2GJ4bvXxnJUViwXKbCEo", "asst_skubi2WGxSHFIq0Yari4Iqow", "asst_x8xlhSAdzRUP1QcQiB8WM9gj2", "asst_8SlJlzeFkhgs5UusPjifLzSi", "asst_DYO3vbs1j5BasLjouZzyf1h0", "asst_gsP467tMXu1sKf1RehdWBs8Y", "asst_EWjMik9D7uCnSqvgpnjY6vX7", "asst_qjip5woBV46XAt67cys3q22j", "asst_tCu1sxNOqWe1oNiSC2R8hVhk", "asst_tC36tKCEYuwJmpMHbEli806C", "asst_cAem1S8ggF5NhfKgVbHbIe29", "asst_zAiLZVDEvV6xOXFtGPDF2KoH", "asst_B5arUibSLlS6WqulQHYWrK7j"]

        for asst_id in lst:
            print(f"\nDeleting {asst_id}...")
            assistant_manager.delete_assistant(asst_id)
