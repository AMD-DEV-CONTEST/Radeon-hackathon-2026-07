package com.doublechaintech.onlinebookstoreservice.book;

import com.doublechaintech.onlinebookstoreservice.Q;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategory;
import com.doublechaintech.onlinebookstoreservice.bookcategory.BookCategoryRequest;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;
import com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreRequest;
import io.teaql.core.AggrFunction;
import io.teaql.core.BaseRequest;
import io.teaql.core.PropertyReference;
import io.teaql.core.SearchCriteria;
import io.teaql.core.SubQuerySearchCriteria;
import io.teaql.core.criteria.Operator;
import io.teaql.core.criteria.TwoOperatorCriteria;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Date;

public class BookRequest<T extends Book> extends BaseRequest<T> {

    /**
     * @deprecated AI agents and business code must use the generated Q facade
     *             instead of constructing request builders directly.
     */
    @Deprecated
    public BookRequest(Class<T> returnType){
        super(returnType);
        selectId();
        selectVersion();
    }

    public BookRequest<T> comment(String comment){
         super.internalComment(comment);
         return this;
    }

    // purpose() 继承自 BaseRequest，返回 ExecutableRequest（终结方法）

    public BookRequest<T> returnType(Class<? extends T> returnType){
        super.setReturnType(returnType);
        return this;
    }

    public BookRequest<T> enableAggregationCache(long cacheExpiredMillis){
        super.enableAggregationCache();
        super.aggregateCacheTime(cacheExpiredMillis);
        return this;
    }

    public BookRequest<T> enableAggregationCache(){
        return enableAggregationCache(0l);
    }


    public BookRequest<T> propagateAggregationCache(long cacheExpiredMillis){
        super.propagateAggregationCache(cacheExpiredMillis);
        return this;
    }

    public BookRequest<T> appendSearchCriteria(SearchCriteria searchCriteria){
        return (BookRequest<T>)super.appendSearchCriteria(searchCriteria);
    }

    public BookRequest<T> filter(String property1, Operator operator, String property2){
        return appendSearchCriteria(new TwoOperatorCriteria(operator, new PropertyReference(property1), new PropertyReference(property2)));
    }


    public BookRequest<T> matchingAnyOf(BookRequest book){
        super.internalMatchAny(book);
        return this;
    }

    public BookRequest<T> enhanceChildrenIfNeeded(){
        return this;
    }

    public BookRequest<T> withDeletedRows(){
        super.withDeletedRows();
        return this;
    }

    public BookRequest<T> deletedRowsOnly(){
        super.deletedRowsOnly();
        return this;
    }

    public BookRequest<T> selectSelf(){
        super.selectSelf();
        return selectId().selectTitle().selectAuthor().selectIsbn().selectPrice().selectStockCount().selectCreateTime().selectUpdateTime().selectBookstoreIdOnly().selectCategoryIdOnly().selectVersion();
    }

    public BookRequest<T> selectSelfFields(){
        return selectSelf();
    }

    public BookRequest<T> selectAll(){
        super.selectAll();
        return selectId().selectTitle().selectAuthor().selectIsbn().selectPrice().selectStockCount().selectCreateTime().selectUpdateTime().selectBookstore().selectCategory().selectVersion();
    }

    public BookRequest<T> selectChildren(){
        super.selectAny();
        return selectId().selectTitle().selectAuthor().selectIsbn().selectPrice().selectStockCount().selectCreateTime().selectUpdateTime().selectBookstore().selectCategory().selectVersion();
    }


    public BookRequest<T> selectId(){
       selectProperty(Book.ID_PROPERTY);
       return this;
    }

    /**
     * fill the id with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  id) to fetch id property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookRequest<T> unselectId(){
       unselectProperty(Book.ID_PROPERTY);
       return this;
    }
    public BookRequest<T> selectTitle(){
       selectProperty(Book.TITLE_PROPERTY);
       return this;
    }

    /**
     * fill the title with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  title) to fetch title property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookRequest<T> unselectTitle(){
       unselectProperty(Book.TITLE_PROPERTY);
       return this;
    }
    public BookRequest<T> selectAuthor(){
       selectProperty(Book.AUTHOR_PROPERTY);
       return this;
    }

    /**
     * fill the author with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  author) to fetch author property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookRequest<T> unselectAuthor(){
       unselectProperty(Book.AUTHOR_PROPERTY);
       return this;
    }
    public BookRequest<T> selectIsbn(){
       selectProperty(Book.ISBN_PROPERTY);
       return this;
    }

    /**
     * fill the isbn with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  isbn) to fetch isbn property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookRequest<T> unselectIsbn(){
       unselectProperty(Book.ISBN_PROPERTY);
       return this;
    }
    public BookRequest<T> selectPrice(){
       selectProperty(Book.PRICE_PROPERTY);
       return this;
    }

    /**
     * fill the price with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  price) to fetch price property.
     * @param rawSqlSegment  customized rawSqlSegment
     */


    /**
     * fill the price with customized aggrFunction, TEAQL uses ({aggrFunction}(price) AS price to fetch price property.
     * @param aggrFunction  aggrFunction
     */
    public BookRequest<T> selectPrice(AggrFunction aggrFunction){
       selectProperty(Book.PRICE_PROPERTY, aggrFunction);
       return this;
    }


    public BookRequest<T> unselectPrice(){
       unselectProperty(Book.PRICE_PROPERTY);
       return this;
    }
    public BookRequest<T> selectStockCount(){
       selectProperty(Book.STOCK_COUNT_PROPERTY);
       return this;
    }

    /**
     * fill the stockCount with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  stockCount) to fetch stockCount property.
     * @param rawSqlSegment  customized rawSqlSegment
     */


    /**
     * fill the stockCount with customized aggrFunction, TEAQL uses ({aggrFunction}(stockCount) AS stockCount to fetch stockCount property.
     * @param aggrFunction  aggrFunction
     */
    public BookRequest<T> selectStockCount(AggrFunction aggrFunction){
       selectProperty(Book.STOCK_COUNT_PROPERTY, aggrFunction);
       return this;
    }


    public BookRequest<T> unselectStockCount(){
       unselectProperty(Book.STOCK_COUNT_PROPERTY);
       return this;
    }
    public BookRequest<T> selectCreateTime(){
       selectProperty(Book.CREATE_TIME_PROPERTY);
       return this;
    }

    /**
     * fill the createTime with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  createTime) to fetch createTime property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookRequest<T> unselectCreateTime(){
       unselectProperty(Book.CREATE_TIME_PROPERTY);
       return this;
    }
    public BookRequest<T> selectUpdateTime(){
       selectProperty(Book.UPDATE_TIME_PROPERTY);
       return this;
    }

    /**
     * fill the updateTime with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  updateTime) to fetch updateTime property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookRequest<T> unselectUpdateTime(){
       unselectProperty(Book.UPDATE_TIME_PROPERTY);
       return this;
    }
    public BookRequest<T> selectBookstoreIdOnly(){
       selectProperty(Book.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookRequest<T> selectBookstore(){
        return selectBookstoreWith(Q.bookstores().unlimited().selectSelf());
    }

    public BookRequest<T> selectBookstoreWith(BookstoreRequest bookstore){
       selectProperty(Book.BOOKSTORE_PROPERTY);
       enhanceRelation(Book.BOOKSTORE_PROPERTY, bookstore);
       return this;
    }

    public BookRequest<T> unselectBookstore(){
       unselectProperty(Book.BOOKSTORE_PROPERTY);
       return this;
    }
    public BookRequest<T> selectCategoryIdOnly(){
       selectProperty(Book.CATEGORY_PROPERTY);
       return this;
    }

    public BookRequest<T> selectCategory(){
        return selectCategoryWith(Q.bookCategories().unlimited().selectSelf());
    }

    public BookRequest<T> selectCategoryWith(BookCategoryRequest category){
       selectProperty(Book.CATEGORY_PROPERTY);
       enhanceRelation(Book.CATEGORY_PROPERTY, category);
       return this;
    }

    public BookRequest<T> unselectCategory(){
       unselectProperty(Book.CATEGORY_PROPERTY);
       return this;
    }
    public BookRequest<T> selectVersion(){
       selectProperty(Book.VERSION_PROPERTY);
       return this;
    }

    /**
     * fill the version with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  version) to fetch version property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookRequest<T> unselectVersion(){
       unselectProperty(Book.VERSION_PROPERTY);
       return this;
    }

    public BookRequest<T> withId(Operator operator, Object... values){
       return appendSearchCriteria(createIdCriteria(operator, values));
    }

    public SearchCriteria createIdCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.ID_PROPERTY, operator, values);
    }

    public BookRequest<T> withIdIs(Long id){
       return withId(Operator.EQUAL, id);
    }
    public BookRequest<T> withIdIn(Long... id){
       return withId(Operator.EQUAL, (Object[])id);
    }



    public BookRequest<T> filterByTitle(String... title){
      if (title == null || title.length == 0) {
        throw new IllegalArgumentException("filterByTitle parameter title cannot be empty");
      }
      return appendSearchCriteria(createTitleCriteria(Operator.EQUAL, (Object[])title));
    }

    public BookRequest<T> withTitle(Operator operator, Object... values){
       return appendSearchCriteria(createTitleCriteria(operator, values));
    }

    public BookRequest<T> withTitleIsUnknown(){
       return withTitle(Operator.IS_NULL);
    }

    public BookRequest<T> withTitleIsKnown(){
       return withTitle(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createTitleCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.TITLE_PROPERTY, operator, values);
    }

    public BookRequest<T> withTitleGreaterThan(String title){
       return withTitle(Operator.GREATER_THAN, title);
    }

    public BookRequest<T> withTitleGreaterThanOrEqualTo(String title){
       return withTitle(Operator.GREATER_THAN_OR_EQUAL, title);
    }

    public BookRequest<T> withTitleLessThan(String title){
       return withTitle(Operator.LESS_THAN, title);
    }

    public BookRequest<T> withTitleLessThanOrEqualTo(String title){
       return withTitle(Operator.LESS_THAN_OR_EQUAL, title);
    }

    public BookRequest<T> withTitleBetween(String startOfTitle, String endOfTitle){
       return withTitle(Operator.BETWEEN, startOfTitle, endOfTitle);
    }
    public BookRequest<T> withTitleStartingWith(String title){
       return withTitle(Operator.BEGIN_WITH, title);
    }
    public BookRequest<T> withTitleContaining(String title){
       return withTitle(Operator.CONTAIN, title);
    }

    public BookRequest<T> withTitleEndingWith(String title){
       return withTitle(Operator.END_WITH, title);
    }

    public BookRequest<T> withTitleIs(String title){
       return withTitle(Operator.EQUAL, title);
    }

    public BookRequest<T> withTitleSoundingLike(String title){
       return withTitle(Operator.SOUNDS_LIKE, title);
    }



    public BookRequest<T> filterByAuthor(String... author){
      if (author == null || author.length == 0) {
        throw new IllegalArgumentException("filterByAuthor parameter author cannot be empty");
      }
      return appendSearchCriteria(createAuthorCriteria(Operator.EQUAL, (Object[])author));
    }

    public BookRequest<T> withAuthor(Operator operator, Object... values){
       return appendSearchCriteria(createAuthorCriteria(operator, values));
    }

    public BookRequest<T> withAuthorIsUnknown(){
       return withAuthor(Operator.IS_NULL);
    }

    public BookRequest<T> withAuthorIsKnown(){
       return withAuthor(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createAuthorCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.AUTHOR_PROPERTY, operator, values);
    }

    public BookRequest<T> withAuthorGreaterThan(String author){
       return withAuthor(Operator.GREATER_THAN, author);
    }

    public BookRequest<T> withAuthorGreaterThanOrEqualTo(String author){
       return withAuthor(Operator.GREATER_THAN_OR_EQUAL, author);
    }

    public BookRequest<T> withAuthorLessThan(String author){
       return withAuthor(Operator.LESS_THAN, author);
    }

    public BookRequest<T> withAuthorLessThanOrEqualTo(String author){
       return withAuthor(Operator.LESS_THAN_OR_EQUAL, author);
    }

    public BookRequest<T> withAuthorBetween(String startOfAuthor, String endOfAuthor){
       return withAuthor(Operator.BETWEEN, startOfAuthor, endOfAuthor);
    }
    public BookRequest<T> withAuthorStartingWith(String author){
       return withAuthor(Operator.BEGIN_WITH, author);
    }
    public BookRequest<T> withAuthorContaining(String author){
       return withAuthor(Operator.CONTAIN, author);
    }

    public BookRequest<T> withAuthorEndingWith(String author){
       return withAuthor(Operator.END_WITH, author);
    }

    public BookRequest<T> withAuthorIs(String author){
       return withAuthor(Operator.EQUAL, author);
    }

    public BookRequest<T> withAuthorSoundingLike(String author){
       return withAuthor(Operator.SOUNDS_LIKE, author);
    }



    public BookRequest<T> filterByIsbn(String... isbn){
      if (isbn == null || isbn.length == 0) {
        throw new IllegalArgumentException("filterByIsbn parameter isbn cannot be empty");
      }
      return appendSearchCriteria(createIsbnCriteria(Operator.EQUAL, (Object[])isbn));
    }

    public BookRequest<T> withIsbn(Operator operator, Object... values){
       return appendSearchCriteria(createIsbnCriteria(operator, values));
    }

    public BookRequest<T> withIsbnIsUnknown(){
       return withIsbn(Operator.IS_NULL);
    }

    public BookRequest<T> withIsbnIsKnown(){
       return withIsbn(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createIsbnCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.ISBN_PROPERTY, operator, values);
    }

    public BookRequest<T> withIsbnGreaterThan(String isbn){
       return withIsbn(Operator.GREATER_THAN, isbn);
    }

    public BookRequest<T> withIsbnGreaterThanOrEqualTo(String isbn){
       return withIsbn(Operator.GREATER_THAN_OR_EQUAL, isbn);
    }

    public BookRequest<T> withIsbnLessThan(String isbn){
       return withIsbn(Operator.LESS_THAN, isbn);
    }

    public BookRequest<T> withIsbnLessThanOrEqualTo(String isbn){
       return withIsbn(Operator.LESS_THAN_OR_EQUAL, isbn);
    }

    public BookRequest<T> withIsbnBetween(String startOfIsbn, String endOfIsbn){
       return withIsbn(Operator.BETWEEN, startOfIsbn, endOfIsbn);
    }
    public BookRequest<T> withIsbnStartingWith(String isbn){
       return withIsbn(Operator.BEGIN_WITH, isbn);
    }
    public BookRequest<T> withIsbnContaining(String isbn){
       return withIsbn(Operator.CONTAIN, isbn);
    }

    public BookRequest<T> withIsbnEndingWith(String isbn){
       return withIsbn(Operator.END_WITH, isbn);
    }

    public BookRequest<T> withIsbnIs(String isbn){
       return withIsbn(Operator.EQUAL, isbn);
    }

    public BookRequest<T> withIsbnSoundingLike(String isbn){
       return withIsbn(Operator.SOUNDS_LIKE, isbn);
    }



    public BookRequest<T> filterByPrice(BigDecimal... price){
      if (price == null || price.length == 0) {
        throw new IllegalArgumentException("filterByPrice parameter price cannot be empty");
      }
      return appendSearchCriteria(createPriceCriteria(Operator.EQUAL, (Object[])price));
    }

    public BookRequest<T> withPrice(Operator operator, Object... values){
       return appendSearchCriteria(createPriceCriteria(operator, values));
    }

    public BookRequest<T> withPriceIsUnknown(){
       return withPrice(Operator.IS_NULL);
    }

    public BookRequest<T> withPriceIsKnown(){
       return withPrice(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createPriceCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.PRICE_PROPERTY, operator, values);
    }

    public BookRequest<T> withPriceGreaterThan(BigDecimal price){
       return withPrice(Operator.GREATER_THAN, price);
    }

    public BookRequest<T> withPriceGreaterThanOrEqualTo(BigDecimal price){
       return withPrice(Operator.GREATER_THAN_OR_EQUAL, price);
    }

    public BookRequest<T> withPriceLessThan(BigDecimal price){
       return withPrice(Operator.LESS_THAN, price);
    }

    public BookRequest<T> withPriceLessThanOrEqualTo(BigDecimal price){
       return withPrice(Operator.LESS_THAN_OR_EQUAL, price);
    }

    public BookRequest<T> withPriceBetween(BigDecimal startOfPrice, BigDecimal endOfPrice){
       return withPrice(Operator.BETWEEN, startOfPrice, endOfPrice);
    }



    public BookRequest<T> filterByStockCount(Integer... stockCount){
      if (stockCount == null || stockCount.length == 0) {
        throw new IllegalArgumentException("filterByStockCount parameter stockCount cannot be empty");
      }
      return appendSearchCriteria(createStockCountCriteria(Operator.EQUAL, (Object[])stockCount));
    }

    public BookRequest<T> withStockCount(Operator operator, Object... values){
       return appendSearchCriteria(createStockCountCriteria(operator, values));
    }

    public BookRequest<T> withStockCountIsUnknown(){
       return withStockCount(Operator.IS_NULL);
    }

    public BookRequest<T> withStockCountIsKnown(){
       return withStockCount(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createStockCountCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.STOCK_COUNT_PROPERTY, operator, values);
    }

    public BookRequest<T> withStockCountGreaterThan(Integer stockCount){
       return withStockCount(Operator.GREATER_THAN, stockCount);
    }

    public BookRequest<T> withStockCountGreaterThanOrEqualTo(Integer stockCount){
       return withStockCount(Operator.GREATER_THAN_OR_EQUAL, stockCount);
    }

    public BookRequest<T> withStockCountLessThan(Integer stockCount){
       return withStockCount(Operator.LESS_THAN, stockCount);
    }

    public BookRequest<T> withStockCountLessThanOrEqualTo(Integer stockCount){
       return withStockCount(Operator.LESS_THAN_OR_EQUAL, stockCount);
    }

    public BookRequest<T> withStockCountBetween(Integer startOfStockCount, Integer endOfStockCount){
       return withStockCount(Operator.BETWEEN, startOfStockCount, endOfStockCount);
    }



    public BookRequest<T> filterByCreateTime(LocalDateTime... createTime){
      if (createTime == null || createTime.length == 0) {
        throw new IllegalArgumentException("filterByCreateTime parameter createTime cannot be empty");
      }
      return appendSearchCriteria(createCreateTimeCriteria(Operator.EQUAL, (Object[])createTime));
    }

    public BookRequest<T> withCreateTime(Operator operator, Object... values){
       return appendSearchCriteria(createCreateTimeCriteria(operator, values));
    }

    public BookRequest<T> withCreateTimeIsUnknown(){
       return withCreateTime(Operator.IS_NULL);
    }

    public BookRequest<T> withCreateTimeIsKnown(){
       return withCreateTime(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createCreateTimeCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.CREATE_TIME_PROPERTY, operator, values);
    }

    public BookRequest<T> withCreateTimeGreaterThan(LocalDateTime createTime){
       return withCreateTime(Operator.GREATER_THAN, createTime);
    }

    public BookRequest<T> withCreateTimeGreaterThanOrEqualTo(LocalDateTime createTime){
       return withCreateTime(Operator.GREATER_THAN_OR_EQUAL, createTime);
    }

    public BookRequest<T> withCreateTimeLessThan(LocalDateTime createTime){
       return withCreateTime(Operator.LESS_THAN, createTime);
    }

    public BookRequest<T> withCreateTimeLessThanOrEqualTo(LocalDateTime createTime){
       return withCreateTime(Operator.LESS_THAN_OR_EQUAL, createTime);
    }

    public BookRequest<T> withCreateTimeBetween(LocalDateTime startOfCreateTime, LocalDateTime endOfCreateTime){
       return withCreateTime(Operator.BETWEEN, startOfCreateTime, endOfCreateTime);
    }
    public BookRequest<T> withCreateTimeBefore(LocalDateTime createTime){
       return withCreateTime(Operator.LESS_THAN, createTime);
    }

    public BookRequest<T> withCreateTimeBefore(Date createTime){
       return withCreateTime(Operator.LESS_THAN, createTime);
    }

    public BookRequest<T> withCreateTimeAfter(LocalDateTime createTime){
       return withCreateTime(Operator.GREATER_THAN, createTime);
    }

    public BookRequest<T> withCreateTimeAfter(Date createTime){
       return withCreateTime(Operator.GREATER_THAN, createTime);
    }

    public BookRequest<T> withCreateTimeBetween(Date startOfCreateTime, Date endOfCreateTime){
       return withCreateTime(Operator.BETWEEN, startOfCreateTime, endOfCreateTime);
    }




    public BookRequest<T> filterByUpdateTime(LocalDateTime... updateTime){
      if (updateTime == null || updateTime.length == 0) {
        throw new IllegalArgumentException("filterByUpdateTime parameter updateTime cannot be empty");
      }
      return appendSearchCriteria(createUpdateTimeCriteria(Operator.EQUAL, (Object[])updateTime));
    }

    public BookRequest<T> withUpdateTime(Operator operator, Object... values){
       return appendSearchCriteria(createUpdateTimeCriteria(operator, values));
    }

    public BookRequest<T> withUpdateTimeIsUnknown(){
       return withUpdateTime(Operator.IS_NULL);
    }

    public BookRequest<T> withUpdateTimeIsKnown(){
       return withUpdateTime(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createUpdateTimeCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.UPDATE_TIME_PROPERTY, operator, values);
    }

    public BookRequest<T> withUpdateTimeGreaterThan(LocalDateTime updateTime){
       return withUpdateTime(Operator.GREATER_THAN, updateTime);
    }

    public BookRequest<T> withUpdateTimeGreaterThanOrEqualTo(LocalDateTime updateTime){
       return withUpdateTime(Operator.GREATER_THAN_OR_EQUAL, updateTime);
    }

    public BookRequest<T> withUpdateTimeLessThan(LocalDateTime updateTime){
       return withUpdateTime(Operator.LESS_THAN, updateTime);
    }

    public BookRequest<T> withUpdateTimeLessThanOrEqualTo(LocalDateTime updateTime){
       return withUpdateTime(Operator.LESS_THAN_OR_EQUAL, updateTime);
    }

    public BookRequest<T> withUpdateTimeBetween(LocalDateTime startOfUpdateTime, LocalDateTime endOfUpdateTime){
       return withUpdateTime(Operator.BETWEEN, startOfUpdateTime, endOfUpdateTime);
    }
    public BookRequest<T> withUpdateTimeBefore(LocalDateTime updateTime){
       return withUpdateTime(Operator.LESS_THAN, updateTime);
    }

    public BookRequest<T> withUpdateTimeBefore(Date updateTime){
       return withUpdateTime(Operator.LESS_THAN, updateTime);
    }

    public BookRequest<T> withUpdateTimeAfter(LocalDateTime updateTime){
       return withUpdateTime(Operator.GREATER_THAN, updateTime);
    }

    public BookRequest<T> withUpdateTimeAfter(Date updateTime){
       return withUpdateTime(Operator.GREATER_THAN, updateTime);
    }

    public BookRequest<T> withUpdateTimeBetween(Date startOfUpdateTime, Date endOfUpdateTime){
       return withUpdateTime(Operator.BETWEEN, startOfUpdateTime, endOfUpdateTime);
    }




    public BookRequest<T> filterByBookstore(Bookstore... bookstore){
      if (bookstore == null || bookstore.length == 0) {
        throw new IllegalArgumentException("filterByBookstore parameter bookstore cannot be empty");
      }
      return appendSearchCriteria(createBookstoreCriteria(Operator.EQUAL, (Object[])bookstore));
    }

    public BookRequest<T> withBookstore(Operator operator, Object... values){
       return appendSearchCriteria(createBookstoreCriteria(operator, values));
    }

    public BookRequest<T> withBookstoreIsUnknown(){
       return withBookstore(Operator.IS_NULL);
    }

    public BookRequest<T> withBookstoreIsKnown(){
       return withBookstore(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createBookstoreCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.BOOKSTORE_PROPERTY, operator, values);
    }

    public BookRequest<T> filterByBookstore(Long bookstore){
      if(bookstore == null){
         return this;
      }
      return withBookstore(Operator.EQUAL, bookstore);
    }
    public BookRequest<T> withBookstoreMatching(BookstoreRequest bookstore){
       return appendSearchCriteria(new SubQuerySearchCriteria(Book.BOOKSTORE_PROPERTY, bookstore, Bookstore.ID_PROPERTY));
    }

    public BookRequest<T> filterByCategory(BookCategory... category){
      if (category == null || category.length == 0) {
        throw new IllegalArgumentException("filterByCategory parameter category cannot be empty");
      }
      return appendSearchCriteria(createCategoryCriteria(Operator.EQUAL, (Object[])category));
    }

    public BookRequest<T> withCategory(Operator operator, Object... values){
       return appendSearchCriteria(createCategoryCriteria(operator, values));
    }

    public BookRequest<T> withCategoryIsUnknown(){
       return withCategory(Operator.IS_NULL);
    }

    public BookRequest<T> withCategoryIsKnown(){
       return withCategory(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createCategoryCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.CATEGORY_PROPERTY, operator, values);
    }

    public BookRequest<T> filterByCategory(Long category){
      if(category == null){
         return this;
      }
      return withCategory(Operator.EQUAL, category);
    }
    public BookRequest<T> withCategoryMatching(BookCategoryRequest category){
       return appendSearchCriteria(new SubQuerySearchCriteria(Book.CATEGORY_PROPERTY, category, BookCategory.ID_PROPERTY));
    }

    public BookRequest<T> filterByVersion(Long... version){
      if (version == null || version.length == 0) {
        throw new IllegalArgumentException("filterByVersion parameter version cannot be empty");
      }
      return appendSearchCriteria(createVersionCriteria(Operator.EQUAL, (Object[])version));
    }

    public BookRequest<T> withVersion(Operator operator, Object... values){
       return appendSearchCriteria(createVersionCriteria(operator, values));
    }

    public BookRequest<T> withVersionIsUnknown(){
       return withVersion(Operator.IS_NULL);
    }

    public BookRequest<T> withVersionIsKnown(){
       return withVersion(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createVersionCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(Book.VERSION_PROPERTY, operator, values);
    }

    public BookRequest<T> withVersionGreaterThan(Long version){
       return withVersion(Operator.GREATER_THAN, version);
    }

    public BookRequest<T> withVersionGreaterThanOrEqualTo(Long version){
       return withVersion(Operator.GREATER_THAN_OR_EQUAL, version);
    }

    public BookRequest<T> withVersionLessThan(Long version){
       return withVersion(Operator.LESS_THAN, version);
    }

    public BookRequest<T> withVersionLessThanOrEqualTo(Long version){
       return withVersion(Operator.LESS_THAN_OR_EQUAL, version);
    }

    public BookRequest<T> withVersionBetween(Long startOfVersion, Long endOfVersion){
       return withVersion(Operator.BETWEEN, startOfVersion, endOfVersion);
    }


    public BookRequest<T> count(){
        super.count();
        return this;
    }
    public BookRequest<T> countAs(String retName){
        super.count(retName);
        return this;
    }
    public BookRequest minPrice(){
        return minPriceAs(prefix("minOf",Book.PRICE_PROPERTY));
    }

    public BookRequest minPriceAs(String retName){
        super.min(retName, Book.PRICE_PROPERTY);
        return this;
    }
    public BookRequest maxPrice(){
        return maxPriceAs(prefix("maxOf",Book.PRICE_PROPERTY));
    }

    public BookRequest maxPriceAs(String retName){
        super.max(retName, Book.PRICE_PROPERTY);
        return this;
    }
    public BookRequest sumPrice(){
        return sumPriceAs(prefix("sumOf",Book.PRICE_PROPERTY));
    }

    public BookRequest sumPriceAs(String retName){
        super.sum(retName, Book.PRICE_PROPERTY);
        return this;
    }
    public BookRequest avgPrice(){
        return avgPriceAs(prefix("avgOf",Book.PRICE_PROPERTY));
    }

    public BookRequest avgPriceAs(String retName){
        super.avg(retName, Book.PRICE_PROPERTY);
        return this;
    }
    public BookRequest standardDeviationPrice(){
        return standardDeviationPriceAs(prefix("standardDeviationOf",Book.PRICE_PROPERTY));
    }

    public BookRequest standardDeviationPriceAs(String retName){
        super.standardDeviation(retName, Book.PRICE_PROPERTY);
        return this;
    }
    public BookRequest squareRootOfPopulationStandardDeviationPrice(){
        return squareRootOfPopulationStandardDeviationPriceAs(prefix("squareRootOfPopulationStandardDeviationOf",Book.PRICE_PROPERTY));
    }

    public BookRequest squareRootOfPopulationStandardDeviationPriceAs(String retName){
        super.squareRootOfPopulationStandardDeviation(retName, Book.PRICE_PROPERTY);
        return this;
    }
    public BookRequest sampleVariancePrice(){
        return sampleVariancePriceAs(prefix("sampleVarianceOf",Book.PRICE_PROPERTY));
    }

    public BookRequest sampleVariancePriceAs(String retName){
        super.sampleVariance(retName, Book.PRICE_PROPERTY);
        return this;
    }
    public BookRequest samplePopulationVariancePrice(){
        return samplePopulationVariancePriceAs(prefix("samplePopulationVarianceOf",Book.PRICE_PROPERTY));
    }

    public BookRequest samplePopulationVariancePriceAs(String retName){
        super.samplePopulationVariance(retName, Book.PRICE_PROPERTY);
        return this;
    }
    public BookRequest minStockCount(){
        return minStockCountAs(prefix("minOf",Book.STOCK_COUNT_PROPERTY));
    }

    public BookRequest minStockCountAs(String retName){
        super.min(retName, Book.STOCK_COUNT_PROPERTY);
        return this;
    }
    public BookRequest maxStockCount(){
        return maxStockCountAs(prefix("maxOf",Book.STOCK_COUNT_PROPERTY));
    }

    public BookRequest maxStockCountAs(String retName){
        super.max(retName, Book.STOCK_COUNT_PROPERTY);
        return this;
    }
    public BookRequest sumStockCount(){
        return sumStockCountAs(prefix("sumOf",Book.STOCK_COUNT_PROPERTY));
    }

    public BookRequest sumStockCountAs(String retName){
        super.sum(retName, Book.STOCK_COUNT_PROPERTY);
        return this;
    }
    public BookRequest avgStockCount(){
        return avgStockCountAs(prefix("avgOf",Book.STOCK_COUNT_PROPERTY));
    }

    public BookRequest avgStockCountAs(String retName){
        super.avg(retName, Book.STOCK_COUNT_PROPERTY);
        return this;
    }
    public BookRequest standardDeviationStockCount(){
        return standardDeviationStockCountAs(prefix("standardDeviationOf",Book.STOCK_COUNT_PROPERTY));
    }

    public BookRequest standardDeviationStockCountAs(String retName){
        super.standardDeviation(retName, Book.STOCK_COUNT_PROPERTY);
        return this;
    }
    public BookRequest squareRootOfPopulationStandardDeviationStockCount(){
        return squareRootOfPopulationStandardDeviationStockCountAs(prefix("squareRootOfPopulationStandardDeviationOf",Book.STOCK_COUNT_PROPERTY));
    }

    public BookRequest squareRootOfPopulationStandardDeviationStockCountAs(String retName){
        super.squareRootOfPopulationStandardDeviation(retName, Book.STOCK_COUNT_PROPERTY);
        return this;
    }
    public BookRequest sampleVarianceStockCount(){
        return sampleVarianceStockCountAs(prefix("sampleVarianceOf",Book.STOCK_COUNT_PROPERTY));
    }

    public BookRequest sampleVarianceStockCountAs(String retName){
        super.sampleVariance(retName, Book.STOCK_COUNT_PROPERTY);
        return this;
    }
    public BookRequest samplePopulationVarianceStockCount(){
        return samplePopulationVarianceStockCountAs(prefix("samplePopulationVarianceOf",Book.STOCK_COUNT_PROPERTY));
    }

    public BookRequest samplePopulationVarianceStockCountAs(String retName){
        super.samplePopulationVariance(retName, Book.STOCK_COUNT_PROPERTY);
        return this;
    }
    public BookRequest<T> groupByBookstoreWithDetails(){
       return groupByBookstoreWithDetails(Q.bookstores().unlimited());
    }

    public BookRequest<T> groupByBookstoreWithDetails(BookstoreRequest subRequest){
       aggregate(Book.BOOKSTORE_PROPERTY, subRequest);
       return this;
    }

    public BookRequest<T> groupByCategoryWithDetails(){
       return groupByCategoryWithDetails(Q.bookCategories().unlimited());
    }

    public BookRequest<T> groupByCategoryWithDetails(BookCategoryRequest subRequest){
       aggregate(Book.CATEGORY_PROPERTY, subRequest);
       return this;
    }



    public BookRequest<T> groupById(){
       groupBy(Book.ID_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByIdAs(String retName){
       groupBy(retName, Book.ID_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByIdWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.ID_PROPERTY, function);
       return this;
    }

    public BookRequest<T> groupByTitle(){
       groupBy(Book.TITLE_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByTitleAs(String retName){
       groupBy(retName, Book.TITLE_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByTitleWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.TITLE_PROPERTY, function);
       return this;
    }

    public BookRequest<T> groupByAuthor(){
       groupBy(Book.AUTHOR_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByAuthorAs(String retName){
       groupBy(retName, Book.AUTHOR_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByAuthorWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.AUTHOR_PROPERTY, function);
       return this;
    }

    public BookRequest<T> groupByIsbn(){
       groupBy(Book.ISBN_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByIsbnAs(String retName){
       groupBy(retName, Book.ISBN_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByIsbnWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.ISBN_PROPERTY, function);
       return this;
    }

    public BookRequest<T> groupByPrice(){
       groupBy(Book.PRICE_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByPriceAs(String retName){
       groupBy(retName, Book.PRICE_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByPriceWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.PRICE_PROPERTY, function);
       return this;
    }

    public BookRequest<T> groupByStockCount(){
       groupBy(Book.STOCK_COUNT_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByStockCountAs(String retName){
       groupBy(retName, Book.STOCK_COUNT_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByStockCountWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.STOCK_COUNT_PROPERTY, function);
       return this;
    }

    public BookRequest<T> groupByCreateTime(){
       groupBy(Book.CREATE_TIME_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByCreateTimeAs(String retName){
       groupBy(retName, Book.CREATE_TIME_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByCreateTimeWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.CREATE_TIME_PROPERTY, function);
       return this;
    }

    public BookRequest<T> groupByUpdateTime(){
       groupBy(Book.UPDATE_TIME_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByUpdateTimeAs(String retName){
       groupBy(retName, Book.UPDATE_TIME_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByUpdateTimeWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.UPDATE_TIME_PROPERTY, function);
       return this;
    }
    public BookRequest<T> groupByBookstoreWith(BookstoreRequest subRequest){
       groupBy(Book.BOOKSTORE_PROPERTY, subRequest);
       return this;
    }
    public BookRequest<T> groupByBookstore(){
       groupBy(Book.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByBookstoreAs(String retName){
       groupBy(retName, Book.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByBookstoreWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.BOOKSTORE_PROPERTY, function);
       return this;
    }
    public BookRequest<T> groupByCategoryWith(BookCategoryRequest subRequest){
       groupBy(Book.CATEGORY_PROPERTY, subRequest);
       return this;
    }
    public BookRequest<T> groupByCategory(){
       groupBy(Book.CATEGORY_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByCategoryAs(String retName){
       groupBy(retName, Book.CATEGORY_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByCategoryWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.CATEGORY_PROPERTY, function);
       return this;
    }

    public BookRequest<T> groupByVersion(){
       groupBy(Book.VERSION_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByVersionAs(String retName){
       groupBy(retName, Book.VERSION_PROPERTY);
       return this;
    }

    public BookRequest<T> groupByVersionWithFunction(String retName, AggrFunction function){
       groupBy(retName, Book.VERSION_PROPERTY, function);
       return this;
    }

    public BookRequest<T> withCategoryIsFiction(){
       filterByCategory(com.doublechaintech.onlinebookstoreservice.Constants.BOOK_CATEGORY_FICTION);
       return this;
    }


    public BookRequest<T> withCategoryIsNonFiction(){
       filterByCategory(com.doublechaintech.onlinebookstoreservice.Constants.BOOK_CATEGORY_NON_FICTION);
       return this;
    }


    public BookRequest<T> withCategoryIsScience(){
       filterByCategory(com.doublechaintech.onlinebookstoreservice.Constants.BOOK_CATEGORY_SCIENCE);
       return this;
    }


    public BookRequest<T> withCategoryIsHistory(){
       filterByCategory(com.doublechaintech.onlinebookstoreservice.Constants.BOOK_CATEGORY_HISTORY);
       return this;
    }




    public BookRequest<T> orderByIdAscending(){
       addOrderByAscending(Book.ID_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByIdDescending(){
       addOrderByDescending(Book.ID_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByTitleAscending(){
       addOrderByAscending(Book.TITLE_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByTitleDescending(){
       addOrderByDescending(Book.TITLE_PROPERTY);
       return this;
    }
    public BookRequest<T> orderByTitleAscendingUsingGBK(){
       addOrderByAscendingUsingGBK(Book.TITLE_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByTitleDescendingUsingGBK(){
       addOrderByDescendingUsingGBK(Book.TITLE_PROPERTY);
       return this;
    }
    public BookRequest<T> orderByAuthorAscending(){
       addOrderByAscending(Book.AUTHOR_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByAuthorDescending(){
       addOrderByDescending(Book.AUTHOR_PROPERTY);
       return this;
    }
    public BookRequest<T> orderByAuthorAscendingUsingGBK(){
       addOrderByAscendingUsingGBK(Book.AUTHOR_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByAuthorDescendingUsingGBK(){
       addOrderByDescendingUsingGBK(Book.AUTHOR_PROPERTY);
       return this;
    }
    public BookRequest<T> orderByIsbnAscending(){
       addOrderByAscending(Book.ISBN_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByIsbnDescending(){
       addOrderByDescending(Book.ISBN_PROPERTY);
       return this;
    }
    public BookRequest<T> orderByIsbnAscendingUsingGBK(){
       addOrderByAscendingUsingGBK(Book.ISBN_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByIsbnDescendingUsingGBK(){
       addOrderByDescendingUsingGBK(Book.ISBN_PROPERTY);
       return this;
    }
    public BookRequest<T> orderByPriceAscending(){
       addOrderByAscending(Book.PRICE_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByPriceDescending(){
       addOrderByDescending(Book.PRICE_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByStockCountAscending(){
       addOrderByAscending(Book.STOCK_COUNT_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByStockCountDescending(){
       addOrderByDescending(Book.STOCK_COUNT_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByCreateTimeAscending(){
       addOrderByAscending(Book.CREATE_TIME_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByCreateTimeDescending(){
       addOrderByDescending(Book.CREATE_TIME_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByUpdateTimeAscending(){
       addOrderByAscending(Book.UPDATE_TIME_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByUpdateTimeDescending(){
       addOrderByDescending(Book.UPDATE_TIME_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByBookstoreAscending(){
       addOrderByAscending(Book.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByBookstoreDescending(){
       addOrderByDescending(Book.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByCategoryAscending(){
       addOrderByAscending(Book.CATEGORY_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByCategoryDescending(){
       addOrderByDescending(Book.CATEGORY_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByVersionAscending(){
       addOrderByAscending(Book.VERSION_PROPERTY);
       return this;
    }

    public BookRequest<T> orderByVersionDescending(){
       addOrderByDescending(Book.VERSION_PROPERTY);
       return this;
    }


    public BookstoreRequest rollUpToBookstore(){
       BookstoreRequest bookstore = Q.bookstores().unlimited();
       this.withBookstoreMatching(bookstore)
           .groupByBookstoreWith(bookstore);
       return bookstore;
    }

    public BookCategoryRequest rollUpToCategory(){
       BookCategoryRequest category = Q.bookCategories().unlimited();
       this.withCategoryMatching(category)
           .groupByCategoryWith(category);
       return category;
    }



   public BookRequest<T> facetByBookstoreAs(String facetName, BookstoreRequest bookstore){
       return facetByBookstoreAs(facetName, bookstore, true);
   }

   public BookRequest<T> facetByBookstoreAs(String facetName, BookstoreRequest bookstore, boolean includeAllFacets){
       addFacet(facetName, Book.BOOKSTORE_PROPERTY, bookstore, includeAllFacets);
       return this;
   }
   public BookRequest<T> facetByCategoryAs(String facetName, BookCategoryRequest category){
       return facetByCategoryAs(facetName, category, true);
   }

   public BookRequest<T> facetByCategoryAs(String facetName, BookCategoryRequest category, boolean includeAllFacets){
       addFacet(facetName, Book.CATEGORY_PROPERTY, category, includeAllFacets);
       return this;
   }


    /**
     * get topN records
     * @param topN  records number
     */
    public BookRequest<T> top(int topN) {
        super.top(topN);
        return this;
    }

    /**
     * get records from offset(inclusive) to offset+size(exclusive)
     * @param offset record offset
     * @param size records number
     */
    public BookRequest<T> offset(int offset, int size) {
        super.offset(offset, size);
        return this;
    }

    /**
     * retrieve all records
     */
    public BookRequest<T> unlimited() {
        super.unlimited();
        return this;
    }

    /**
     * get records of one page
     * @param pageNumber page number(1-based)
     * @param pageSize page size
     */
    public BookRequest<T> page(int pageNumber, int pageSize) {
        int offset = (pageNumber - 1) * pageSize;
        return offset(offset, pageSize);
   }

    /**
     * get records of one page, default page size is 10
     * @param pageNumber page number(1-based)
     */
    public BookRequest<T> page(int pageNumber) {
        return page(pageNumber, 10);
   }
}