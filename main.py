from src.ai_modules.cv_extractor import CVExtractor
from src.ai_modules.cv_parser import CVParser
# from src.scrapers.tanitjobs import TanitJobsScraper
# from src.scrapers.linkedin import LinkedInScraper

from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="qwen2.5:7b",
    temperature=0
)
print(llm.model)

if __name__ == "__main__":

    # bot_linkedin = LinkedInScraper()
    
    # bot_linkedin.start_browser()  
    # bot_linkedin.login()          
    # bot_linkedin.search_and_collect_links("Python Developer")
    # bot_linkedin.extract_job_list()

    # bot_linkedin.close_browser()


    # tanitjobs_scraper = TanitJobsScraper()
    # tanitjobs_scraper.start_browser()
    # tanitjobs_scraper.login()
    # tanitjobs_scraper.close_browser()
    # print(dir(tanitjobs_scraper))

    cv_parser = CVParser("example_cv.pdf")
    document = cv_parser.extract_text()
    extractor = CVExtractor(llm=llm, debug=False)
    candidate = extractor.extract(document)

    print(candidate)
    