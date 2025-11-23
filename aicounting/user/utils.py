# System imports
import json
import os
import time
from pathlib import Path

# Third-party imports
from django.db import models
import pandas as pd

# Local imports
from aicounting.openai_client import OpeAIClient
from user.models import DimAICClient, DimAICAssistant


class OpenAIAssistant(OpeAIClient):
    
    def __init__(self, api_key, customer=None, client_obj=None, client_id=None, special_rules=None):
        super().__init__(api_key)
        self.customer = customer
        self.client_obj = client_obj
        self.client_id = client_id
        self.aic_client = None
        self.vector_store_id = None
        self.assistant_id = None
        self.schema_path = "user/schemas/default_schema.json"
        self.response_schema = ""
        
        # Set model parameters
        self.temperature = 1.0
        self.top_p = 1.0

        self.assistant_instructions = f"""You are a Bookkeeping Assistant API responsible for accurately coding financial transactions based on historical data and organizational guidelines. You will be provided with:
            Chart of Accounts (COA): A comprehensive list of all GL accounts, each with a unique account number, account type, and description.
            Vendor Mapping List: A directory linking vendors to their typical GL accounts, including notes on transaction context or specific usage rules.
            General Ledger History: Historical GL transactions, including dates, descriptions, vendor names, amounts, and accounts used.

            Objectives:
            Transaction Classification: Assign each transaction to the appropriate GL account from the chart of accounts that has been uploaded to you.  Do not rely on the category in the transaction.  Use your own logic.

            Only use accounts listed in the chart of accounts.  Do not assume and do not hallucinate.
            Only use the descriptions provided in the chart of accounts.  Do not make up your own.
            Do not ask questions. Return only the requested structured output in plain text. No explanations.

            **instructions to handle transactions that you are not confident about**

            Return the data with the following nine columns:  
            **{{
                id: "1",
                "description": "item_description",
                "gl_account": "suspense/etc",
                "gl_account_desc" :".......",
                "confidence score": 0.89
                }}**

            - Date is the date that is provided.
            - Description is the description provided as is.
            - Party is derived from the description.  It is company, person or any entity that this transaction is related to.
            - gl_account is the account that this transaction is mapped to.  Only use accounts listed in the char of accounts.  Do not assume and do not hallucinate.
            - gl_account_desc is the account description of the above gl_account from the chart of accounts 
            - confidence score is the score of how confident you are in the classification
        """

        if special_rules:
            self.assistant_instructions += f"\n**Special Rules**:\n{special_rules}"

    def load_response_schema(self, schema_path=None):
        """Load JSON schema for response format"""
        if not schema_path:
            schema_path = self.schema_path
            
        if schema_path and os.path.exists(schema_path):
            with open(schema_path, 'r') as f:
                self.response_schema = json.load(f)
        return None

    def create_vector_store(self, client_documents):
        """Create a vector store with client documents from Azure storage, converting CSV to JSON"""
        try:
            # Create vector store
            vector_store = self.client.vector_stores.create(
                name=f"Client_{self.client_id}_Documents"
            )
            
            # Process and upload files to vector store from Azure storage
            file_streams = []
            from django.core.files.storage import default_storage
            
            for doc in client_documents:
                if doc.file:
                    try:
                        # Download file from Azure storage
                        with default_storage.open(doc.file.name, 'rb') as azure_file:
                            file_content = azure_file.read()
                        
                        # Get file extension to determine processing method
                        file_name = doc.file.name.split('/')[-1]
                        file_extension = file_name.lower().split('.')[-1]
                        
                        # Process based on file type
                        if file_extension == 'csv':
                            # Convert CSV to JSON
                            processed_content = self._convert_csv_to_json(file_content, doc.document_type, file_name)
                            if processed_content:
                                # Create JSON file stream
                                import io
                                json_content = json.dumps(processed_content, indent=2)
                                file_stream = io.BytesIO(json_content.encode('utf-8'))
                                # Change extension to .json for vector store
                                json_filename = file_name.rsplit('.', 1)[0] + '.json'
                                file_stream.name = json_filename
                                file_streams.append(file_stream)
                                
                                # Save the JSON version to Azure storage for future reference
                                self._save_json_to_azure(json_content, doc, json_filename)
                        
                        elif file_extension in ['xlsx', 'xls']:
                            # Convert Excel to JSON
                            processed_content = self._convert_excel_to_json(file_content, doc.document_type, file_name)
                            if processed_content:
                                # Create JSON file stream
                                import io
                                json_content = json.dumps(processed_content, indent=2)
                                file_stream = io.BytesIO(json_content.encode('utf-8'))
                                # Change extension to .json for vector store
                                json_filename = file_name.rsplit('.', 1)[0] + '.json'
                                file_stream.name = json_filename
                                file_streams.append(file_stream)
                                
                                # Save the JSON version to Azure storage for future reference
                                self._save_json_to_azure(json_content, doc, json_filename)
                        
                        else:
                            # For other file types (PDF, TXT, etc.), upload as-is
                            import io
                            file_stream = io.BytesIO(file_content)
                            file_stream.name = file_name
                            file_streams.append(file_stream)
                            
                    except Exception as e:
                        print(f"Error processing file {doc.file.name}: {e}")
            
            if file_streams:
                file_batch = self.client.vector_stores.file_batches.upload_and_poll(
                    vector_store_id=vector_store.id,
                    files=file_streams
                )
                
                # Close file streams
                for stream in file_streams:
                    stream.close()
                    
                print(f"Vector store created with {len(file_streams)} files")
            
            return vector_store.id
            
        except Exception as e:
            print(f"Error creating vector store: {e}")
            return None
    
    def _convert_csv_to_json(self, file_content, document_type, filename):
        """Convert CSV content to structured JSON format"""
        try:
            import io
            
            # Read CSV content
            csv_content = file_content.decode('utf-8')
            df = pd.read_csv(io.StringIO(csv_content))
            
            # Structure the JSON based on document type
            if document_type == "chart_of_account":
                json_data = {
                    "document_type": "Chart of Accounts",
                    "filename": filename,
                    "description": "Chart of Accounts containing GL account codes, classes, and descriptions",
                    "accounts": []
                }
                
                for _, row in df.iterrows():
                    account_data = {}
                    # Handle different possible column names
                    for col in df.columns:
                        col_lower = col.lower().strip()
                        if 'gl_code' in col_lower or 'account_code' in col_lower or 'code' in col_lower:
                            account_data['gl_code'] = str(row[col]).strip() if pd.notna(row[col]) else ""
                        elif 'class' in col_lower and 'sub' not in col_lower:
                            account_data['account_class'] = str(row[col]).strip() if pd.notna(row[col]) else ""
                        elif 'subclass' in col_lower or 'sub_class' in col_lower:
                            account_data['sub_class'] = str(row[col]).strip() if pd.notna(row[col]) else ""
                        elif 'description' in col_lower or 'name' in col_lower:
                            account_data['description'] = str(row[col]).strip() if pd.notna(row[col]) else ""
                        else:
                            # Include any other columns as-is
                            account_data[col] = str(row[col]).strip() if pd.notna(row[col]) else ""
                    
                    json_data["accounts"].append(account_data)
                
            elif document_type == "vendor_list":
                json_data = {
                    "document_type": "Vendor List",
                    "filename": filename,
                    "description": "List of vendors with their associated GL accounts and mapping rules",
                    "vendors": []
                }
                
                for _, row in df.iterrows():
                    vendor_data = {}
                    for col in df.columns:
                        vendor_data[col.lower().replace(' ', '_')] = str(row[col]).strip() if pd.notna(row[col]) else ""
                    json_data["vendors"].append(vendor_data)
                    
            elif document_type == "gl_history":
                json_data = {
                    "document_type": "GL History",
                    "filename": filename,
                    "description": "Historical general ledger transactions showing patterns of account usage",
                    "transactions": []
                }
                
                for _, row in df.iterrows():
                    transaction_data = {}
                    for col in df.columns:
                        col_key = col.lower().replace(' ', '_')
                        transaction_data[col_key] = str(row[col]).strip() if pd.notna(row[col]) else ""
                    json_data["transactions"].append(transaction_data)
                    
            else:
                # Generic format for unknown document types
                json_data = {
                    "document_type": document_type,
                    "filename": filename,
                    "description": f"Data from {filename}",
                    "data": df.to_dict('records')
                }
            
            return json_data
            
        except Exception as e:
            print(f"Error converting CSV to JSON for {filename}: {e}")
            return None
    
    def _convert_excel_to_json(self, file_content, document_type, filename):
        """Convert Excel content to structured JSON format"""
        try:
            import io
            
            # Read Excel content
            excel_file = io.BytesIO(file_content)
            
            # Try to read all sheets
            xl_file = pd.ExcelFile(excel_file)
            sheets_data = {}
            
            for sheet_name in xl_file.sheet_names:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                
                if document_type == "chart_of_account":
                    sheet_data = {
                        "sheet_name": sheet_name,
                        "accounts": []
                    }
                    
                    for _, row in df.iterrows():
                        account_data = {}
                        for col in df.columns:
                            col_lower = col.lower().strip()
                            if 'gl_code' in col_lower or 'account_code' in col_lower or 'code' in col_lower:
                                account_data['gl_code'] = str(row[col]).strip() if pd.notna(row[col]) else ""
                            elif 'class' in col_lower and 'sub' not in col_lower:
                                account_data['account_class'] = str(row[col]).strip() if pd.notna(row[col]) else ""
                            elif 'subclass' in col_lower or 'sub_class' in col_lower:
                                account_data['sub_class'] = str(row[col]).strip() if pd.notna(row[col]) else ""
                            elif 'description' in col_lower or 'name' in col_lower:
                                account_data['description'] = str(row[col]).strip() if pd.notna(row[col]) else ""
                            else:
                                account_data[col] = str(row[col]).strip() if pd.notna(row[col]) else ""
                        
                        sheet_data["accounts"].append(account_data)
                
                else:
                    # Generic format for other document types
                    sheet_data = {
                        "sheet_name": sheet_name,
                        "data": df.to_dict('records')
                    }
                
                sheets_data[sheet_name] = sheet_data
            
            json_data = {
                "document_type": document_type,
                "filename": filename,
                "description": f"Excel data from {filename}",
                "sheets": sheets_data
            }
            
            return json_data
            
        except Exception as e:
            print(f"Error converting Excel to JSON for {filename}: {e}")
            return None
    
    def _save_json_to_azure(self, json_content, original_doc, json_filename):
        """Save the JSON version of the file to Azure storage for future reference"""
        try:
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            
            # Create path in processed_documents folder
            if self.customer and self.client_obj:
                json_path = f"customer_{self.customer.customer_name.lower().replace(' ', '_')}_{self.customer.id}/client_{self.client_obj.client_name.lower().replace(' ', '_')}_{self.client_obj.id}/processed_documents/{json_filename}"
            else:
                json_path = f"processed_documents/client_{self.client_id}/{json_filename}"
            
            # Save to Azure storage
            default_storage.save(json_path, ContentFile(json_content.encode('utf-8')))
            print(f"Saved JSON version to Azure: {json_path}")
            
        except Exception as e:
            print(f"Error saving JSON to Azure for {json_filename}: {e}")

    def provison_client_assistant(self):
        """
        Gathers client-specific information such as COA, Vendor Mapping, and GL History.
        """
        if not self.client_id:
            raise ValueError("client_id must be set before gathering information")
            
        try:
            # Get the AIC Client object
            self.aic_client = DimAICClient.objects.get(client_id=self.client_id)
            
            # Get client documents
            client_documents = self.aic_client.documents.all()
            
            # Check if assistant already exists
            assistant_config, created = DimAICAssistant.objects.get_or_create(
                client=self.aic_client,
                defaults={
                    'assistant_name': f"Bookkeeping Assistant - {self.aic_client.client_name}",
                    'model_name': self.model,
                    'temperature': self.temperature,
                    'top_p': self.top_p,
                    'response_schema': self.response_schema,
                }
            )
            
            if created or not assistant_config.vector_store_id:
                # Create vector store with client documents
                vector_store_id = self.create_vector_store(client_documents)
                if vector_store_id:
                    assistant_config.vector_store_id = vector_store_id
                    self.vector_store_id = vector_store_id
                    
            if created or not assistant_config.assistant_id:
                self.load_response_schema()
                assistant_config.response_schema = self.response_schema
                # Create OpenAI assistant
                assistant = self.create_assistant(
                    name=assistant_config.assistant_name,
                    description=f"Bookkeeping assistant for {self.aic_client.client_name}"
                )
                if assistant:
                    assistant_config.assistant_id = assistant.id
                    self.assistant_id = assistant.id
                    
            assistant_config.save()
            
            # Set instance variables
            self.vector_store_id = assistant_config.vector_store_id
            self.assistant_id = assistant_config.assistant_id
            
            return assistant_config
            
        except DimAICClient.DoesNotExist:
            raise ValueError(f"Client with ID {self.client_id} not found")
        except Exception as e:
            print(f"Error gathering client information: {e}")
            raise

    def create_assistant(self, name: str, description: str = None):
        """Create OpenAI assistant with file search tools"""
        try:
            
            # Prepare assistant parameters
            assistant_params = {
                'name': name,
                'description': description or f"Bookkeeping Assistant for {name}",
                'model': self.model,
                'instructions': self.assistant_instructions,
                'tools': [{"type": "file_search"}],  # Enable file search
                'temperature': self.temperature,
                'top_p': self.top_p,
            }
            
            # Add response format if schema is available
            if self.response_schema:
                assistant_params['response_format'] = {
                    "type": "json_schema",
                    "json_schema": self.response_schema
                }
            
            # Add vector store if available
            if self.vector_store_id:
                assistant_params['tool_resources'] = {
                    "file_search": {
                        "vector_store_ids": [self.vector_store_id]
                    }
                }
            
            # print("assistant_params :: ", assistant_params)
            assistant = self.client.beta.assistants.create(**assistant_params)
            return assistant
            
        except Exception as e:
            print(f"Error creating assistant: {e}")
            return None

    def get_or_create_assistant_config(self):
        """Get existing assistant configuration or create new one"""
        if not self.aic_client:
            raise ValueError("AIC Client must be set before getting assistant config")
            
        try:
            return DimAICAssistant.objects.get(client=self.aic_client, is_active=True)
        except DimAICAssistant.DoesNotExist:
            return None

    def update_assistant_with_new_files(self, new_document_ids=[]):
        """
        Updates an existing assistant's vector store with new client documents.
        This function is used when a client adds additional files after the initial setup.
        
        Args:
            new_documents: List of new document objects to add. If None, will add all client documents.
        
        Returns:
            bool: True if update was successful, False otherwise
        """
        if not self.client_id:
            raise ValueError("client_id must be set before updating assistant")
            
        try:
            # Get the AIC Client object if not already set
            if not self.aic_client:
                self.aic_client = DimAICClient.objects.get(client_id=self.client_id)
            
            # Get existing assistant configuration
            assistant_config = self.get_or_create_assistant_config()
            if not assistant_config:
                raise ValueError(f"No existing assistant found for client {self.client_id}")
            
            # Set instance variables from existing config
            self.vector_store_id = assistant_config.vector_store_id
            self.assistant_id = assistant_config.assistant_id
            
            if not self.vector_store_id:
                print("No existing vector store found. Creating new one...")
                # If no vector store exists, create one with all documents
                client_documents = self.aic_client.documents.all()
                vector_store_id = self.create_vector_store(client_documents)
                if vector_store_id:
                    assistant_config.vector_store_id = vector_store_id
                    assistant_config.save()
                    self.vector_store_id = vector_store_id
                return vector_store_id is not None
            
            documents_to_add = self.aic_client.documents.filter(
                    id__in=new_document_ids
                )
            
            # Filter documents that have valid file paths
            valid_documents = []
            for doc in documents_to_add:
                if doc.file:
                    valid_documents.append(doc)
            
            if not valid_documents:
                print("No valid documents found to add to vector store")
                return True
            
            # Add new files to existing vector store from Azure storage
            file_streams = []
            from django.core.files.storage import default_storage
            
            try:
                for doc in valid_documents:
                    try:
                        # Download file from Azure storage
                        with default_storage.open(doc.file.name, 'rb') as azure_file:
                            file_content = azure_file.read()
                        
                        # Get file extension to determine processing method
                        file_name = doc.file.name.split('/')[-1]
                        file_extension = file_name.lower().split('.')[-1]
                        
                        # Process based on file type (same logic as create_vector_store)
                        if file_extension == 'csv':
                            # Convert CSV to JSON
                            processed_content = self._convert_csv_to_json(file_content, doc.document_type, file_name)
                            if processed_content:
                                # Create JSON file stream
                                import io
                                json_content = json.dumps(processed_content, indent=2)
                                file_stream = io.BytesIO(json_content.encode('utf-8'))
                                # Change extension to .json for vector store
                                json_filename = file_name.rsplit('.', 1)[0] + '.json'
                                file_stream.name = json_filename
                                file_streams.append(file_stream)
                                
                                # Save the JSON version to Azure storage for future reference
                                self._save_json_to_azure(json_content, doc, json_filename)
                        
                        elif file_extension in ['xlsx', 'xls']:
                            # Convert Excel to JSON
                            processed_content = self._convert_excel_to_json(file_content, doc.document_type, file_name)
                            if processed_content:
                                # Create JSON file stream
                                import io
                                json_content = json.dumps(processed_content, indent=2)
                                file_stream = io.BytesIO(json_content.encode('utf-8'))
                                # Change extension to .json for vector store
                                json_filename = file_name.rsplit('.', 1)[0] + '.json'
                                file_stream.name = json_filename
                                file_streams.append(file_stream)
                                
                                # Save the JSON version to Azure storage for future reference
                                self._save_json_to_azure(json_content, doc, json_filename)
                        
                        else:
                            # For other file types (PDF, TXT, etc.), upload as-is
                            import io
                            file_stream = io.BytesIO(file_content)
                            file_stream.name = file_name
                            file_streams.append(file_stream)
                            
                    except Exception as e:
                        print(f"Error processing file {doc.file.name}: {e}")
                
                if file_streams:
                    file_batch = self.client.vector_stores.file_batches.upload_and_poll(
                        vector_store_id=self.vector_store_id,
                        files=file_streams
                    )
                    
                    print(f"Added {len(file_streams)} new files to vector store {self.vector_store_id}")
                    
                    # Update the assistant to ensure it uses the updated vector store
                    if self.assistant_id:
                        assistant_update = self.client.beta.assistants.update(
                            assistant_id=self.assistant_id,
                            tool_resources={
                                "file_search": {
                                    "vector_store_ids": [self.vector_store_id]
                                }
                            }
                        )
                        print(f"Updated assistant {self.assistant_id} with new files")
                    
                    return True
                    
            except Exception as e:
                print(f"Error adding files to vector store: {e}")
                return False
            finally:
                # Always close file streams
                for stream in file_streams:
                    if not stream.closed:
                        stream.close()
            
            return True
            
        except DimAICClient.DoesNotExist:
            raise ValueError(f"Client with ID {self.client_id} not found")
        except Exception as e:
            print(f"Error updating assistant with new files: {e}")
            return False
