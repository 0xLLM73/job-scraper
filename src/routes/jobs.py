from flask import Blueprint, request, jsonify
import json
import os
import logging
from typing import List, Dict, Any
import threading
import time

from src.job_scraper import JobScraper
from src.supabase_integration import SupabaseJobStorage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

jobs_bp = Blueprint('jobs', __name__)

# Global variables for configuration
FIRECRAWL_API_KEY = "fc-71a56bd82c06478eb8803c65abbfb0d3"
SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')

# Initialize services
scraper = JobScraper(FIRECRAWL_API_KEY)
storage = None

# Global variable to track scraping sessions
scraping_sessions = {}

def get_storage():
    """Get or initialize Supabase storage"""
    global storage
    if storage is None and SUPABASE_URL and SUPABASE_KEY:
        storage = SupabaseJobStorage(SUPABASE_URL, SUPABASE_KEY)
    return storage

@jobs_bp.route('/scrape', methods=['POST'])
def scrape_jobs():
    """Endpoint to scrape job postings"""
    try:
        data = request.get_json()
        urls = data.get('urls', [])
        
        if not urls:
            return jsonify({'error': 'No URLs provided'}), 400
        
        # Generate session ID
        session_id = f"session_{int(time.time())}"
        
        # Start scraping in background thread
        def scrape_background():
            try:
                scraping_sessions[session_id] = {
                    'status': 'running',
                    'total_urls': len(urls),
                    'completed': 0,
                    'results': [],
                    'errors': []
                }
                
                results = []
                for i, url in enumerate(urls):
                    try:
                        logger.info(f"Scraping job {i+1}/{len(urls)}: {url}")
                        result = scraper.scrape_job(url)
                        
                        if result:
                            results.append(result)
                            
                            # Store in Supabase if configured
                            storage_client = get_storage()
                            if storage_client:
                                job_id = storage_client.store_complete_job(result)
                                if job_id:
                                    result['stored_job_id'] = job_id
                        
                        scraping_sessions[session_id]['completed'] = i + 1
                        scraping_sessions[session_id]['results'] = results
                        
                    except Exception as e:
                        error_msg = f"Error scraping {url}: {str(e)}"
                        logger.error(error_msg)
                        scraping_sessions[session_id]['errors'].append(error_msg)
                
                scraping_sessions[session_id]['status'] = 'completed'
                logger.info(f"Scraping session {session_id} completed")
                
            except Exception as e:
                scraping_sessions[session_id]['status'] = 'failed'
                scraping_sessions[session_id]['errors'].append(str(e))
                logger.error(f"Scraping session {session_id} failed: {e}")
        
        # Start background thread
        thread = threading.Thread(target=scrape_background)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'session_id': session_id,
            'status': 'started',
            'message': f'Started scraping {len(urls)} job postings'
        })
        
    except Exception as e:
        logger.error(f"Error in scrape_jobs endpoint: {e}")
        return jsonify({'error': str(e)}), 500

@jobs_bp.route('/scrape/status/<session_id>', methods=['GET'])
def get_scraping_status(session_id):
    """Get the status of a scraping session"""
    try:
        if session_id not in scraping_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session_data = scraping_sessions[session_id]
        
        return jsonify({
            'session_id': session_id,
            'status': session_data['status'],
            'total_urls': session_data['total_urls'],
            'completed': session_data['completed'],
            'success_count': len(session_data['results']),
            'error_count': len(session_data['errors']),
            'errors': session_data['errors']
        })
        
    except Exception as e:
        logger.error(f"Error getting scraping status: {e}")
        return jsonify({'error': str(e)}), 500

@jobs_bp.route('/scrape/results/<session_id>', methods=['GET'])
def get_scraping_results(session_id):
    """Get the results of a scraping session"""
    try:
        if session_id not in scraping_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session_data = scraping_sessions[session_id]
        
        return jsonify({
            'session_id': session_id,
            'status': session_data['status'],
            'results': session_data['results']
        })
        
    except Exception as e:
        logger.error(f"Error getting scraping results: {e}")
        return jsonify({'error': str(e)}), 500

@jobs_bp.route('/jobs', methods=['GET'])
def get_jobs():
    """Get all jobs from Supabase"""
    try:
        storage_client = get_storage()
        if not storage_client:
            return jsonify({'error': 'Supabase not configured'}), 500
        
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        jobs = storage_client.get_all_jobs(limit=limit, offset=offset)
        
        return jsonify({
            'jobs': jobs,
            'count': len(jobs),
            'limit': limit,
            'offset': offset
        })
        
    except Exception as e:
        logger.error(f"Error getting jobs: {e}")
        return jsonify({'error': str(e)}), 500

@jobs_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job_details(job_id):
    """Get detailed job information including form structure"""
    try:
        storage_client = get_storage()
        if not storage_client:
            return jsonify({'error': 'Supabase not configured'}), 500
        
        job_data = storage_client.get_job_with_form(job_id)
        
        if not job_data:
            return jsonify({'error': 'Job not found'}), 404
        
        return jsonify(job_data)
        
    except Exception as e:
        logger.error(f"Error getting job details: {e}")
        return jsonify({'error': str(e)}), 500

@jobs_bp.route('/jobs/search', methods=['GET'])
def search_jobs():
    """Search jobs by query"""
    try:
        storage_client = get_storage()
        if not storage_client:
            return jsonify({'error': 'Supabase not configured'}), 500
        
        query = request.args.get('q', '')
        limit = request.args.get('limit', 50, type=int)
        
        if not query:
            return jsonify({'error': 'Query parameter required'}), 400
        
        jobs = storage_client.search_jobs(query, limit=limit)
        
        return jsonify({
            'jobs': jobs,
            'query': query,
            'count': len(jobs)
        })
        
    except Exception as e:
        logger.error(f"Error searching jobs: {e}")
        return jsonify({'error': str(e)}), 500

@jobs_bp.route('/jobs/<job_id>/interact', methods=['POST'])
def log_interaction(job_id):
    """Log user interaction with a job"""
    try:
        storage_client = get_storage()
        if not storage_client:
            return jsonify({'error': 'Supabase not configured'}), 500
        
        data = request.get_json()
        user_id = data.get('user_id', 'anonymous')
        interaction_type = data.get('interaction_type', 'view')
        interaction_data = data.get('interaction_data', {})
        
        success = storage_client.log_user_interaction(
            job_id, user_id, interaction_type, interaction_data
        )
        
        if success:
            return jsonify({'message': 'Interaction logged successfully'})
        else:
            return jsonify({'error': 'Failed to log interaction'}), 500
        
    except Exception as e:
        logger.error(f"Error logging interaction: {e}")
        return jsonify({'error': str(e)}), 500

@jobs_bp.route('/config', methods=['GET'])
def get_config():
    """Get configuration status"""
    return jsonify({
        'firecrawl_configured': bool(FIRECRAWL_API_KEY),
        'supabase_configured': bool(SUPABASE_URL and SUPABASE_KEY),
        'supabase_connected': get_storage() is not None and get_storage().test_connection() if get_storage() else False
    })

@jobs_bp.route('/demo/scrape', methods=['POST'])
def demo_scrape():
    """Demo endpoint that scrapes without storing in Supabase"""
    try:
        data = request.get_json()
        urls = data.get('urls', [])
        
        if not urls:
            return jsonify({'error': 'No URLs provided'}), 400
        
        results = []
        for url in urls:
            try:
                result = scraper.scrape_job(url)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Error scraping {url}: {e}")
        
        return jsonify({
            'results': results,
            'count': len(results),
            'message': f'Successfully scraped {len(results)}/{len(urls)} jobs'
        })
        
    except Exception as e:
        logger.error(f"Error in demo scrape: {e}")
        return jsonify({'error': str(e)}), 500

