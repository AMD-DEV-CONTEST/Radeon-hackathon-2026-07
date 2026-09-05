package com.doublechaintech.onlinebookstoreservice.bookcategory;

import com.doublechaintech.onlinebookstoreservice.Q;
import com.doublechaintech.onlinebookstoreservice.book.Book;
import com.doublechaintech.onlinebookstoreservice.book.BookRequest;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;
import com.doublechaintech.onlinebookstoreservice.bookstore.BookstoreRequest;
import io.teaql.core.AggrFunction;
import io.teaql.core.BaseRequest;
import io.teaql.core.PropertyReference;
import io.teaql.core.SearchCriteria;
import io.teaql.core.SubQuerySearchCriteria;
import io.teaql.core.criteria.Operator;
import io.teaql.core.criteria.TwoOperatorCriteria;

public class BookCategoryRequest<T extends BookCategory> extends BaseRequest<T> {

    /**
     * @deprecated AI agents and business code must use the generated Q facade
     *             instead of constructing request builders directly.
     */
    @Deprecated
    public BookCategoryRequest(Class<T> returnType){
        super(returnType);
        selectId();
        selectVersion();
    }

    public BookCategoryRequest<T> comment(String comment){
         super.internalComment(comment);
         return this;
    }

    // purpose() 继承自 BaseRequest，返回 ExecutableRequest（终结方法）

    public BookCategoryRequest<T> returnType(Class<? extends T> returnType){
        super.setReturnType(returnType);
        return this;
    }

    public BookCategoryRequest<T> enableAggregationCache(long cacheExpiredMillis){
        super.enableAggregationCache();
        super.aggregateCacheTime(cacheExpiredMillis);
        return this;
    }

    public BookCategoryRequest<T> enableAggregationCache(){
        return enableAggregationCache(0l);
    }


    public BookCategoryRequest<T> propagateAggregationCache(long cacheExpiredMillis){
        super.propagateAggregationCache(cacheExpiredMillis);
        return this;
    }

    public BookCategoryRequest<T> appendSearchCriteria(SearchCriteria searchCriteria){
        return (BookCategoryRequest<T>)super.appendSearchCriteria(searchCriteria);
    }

    public BookCategoryRequest<T> filter(String property1, Operator operator, String property2){
        return appendSearchCriteria(new TwoOperatorCriteria(operator, new PropertyReference(property1), new PropertyReference(property2)));
    }


    public BookCategoryRequest<T> matchingAnyOf(BookCategoryRequest bookCategory){
        super.internalMatchAny(bookCategory);
        return this;
    }

    public BookCategoryRequest<T> enhanceChildrenIfNeeded(){
        return this;
    }

    public BookCategoryRequest<T> withDeletedRows(){
        super.withDeletedRows();
        return this;
    }

    public BookCategoryRequest<T> deletedRowsOnly(){
        super.deletedRowsOnly();
        return this;
    }

    public BookCategoryRequest<T> selectSelf(){
        super.selectSelf();
        return selectId().selectName().selectCode().selectBookstoreIdOnly().selectVersion();
    }

    public BookCategoryRequest<T> selectSelfFields(){
        return selectSelf();
    }

    public BookCategoryRequest<T> selectAll(){
        super.selectAll();
        return selectId().selectName().selectCode().selectBookstore().selectVersion();
    }

    public BookCategoryRequest<T> selectChildren(){
        super.selectAny();
        selectBookList();
        return selectId().selectName().selectCode().selectBookstore().selectVersion();
    }


    public BookCategoryRequest<T> selectId(){
       selectProperty(BookCategory.ID_PROPERTY);
       return this;
    }

    /**
     * fill the id with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  id) to fetch id property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookCategoryRequest<T> unselectId(){
       unselectProperty(BookCategory.ID_PROPERTY);
       return this;
    }
    public BookCategoryRequest<T> selectName(){
       selectProperty(BookCategory.NAME_PROPERTY);
       return this;
    }

    /**
     * fill the name with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  name) to fetch name property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookCategoryRequest<T> unselectName(){
       unselectProperty(BookCategory.NAME_PROPERTY);
       return this;
    }
    public BookCategoryRequest<T> selectCode(){
       selectProperty(BookCategory.CODE_PROPERTY);
       return this;
    }

    /**
     * fill the code with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  code) to fetch code property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookCategoryRequest<T> unselectCode(){
       unselectProperty(BookCategory.CODE_PROPERTY);
       return this;
    }
    public BookCategoryRequest<T> selectBookstoreIdOnly(){
       selectProperty(BookCategory.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> selectBookstore(){
        return selectBookstoreWith(Q.bookstores().unlimited().selectSelf());
    }

    public BookCategoryRequest<T> selectBookstoreWith(BookstoreRequest bookstore){
       selectProperty(BookCategory.BOOKSTORE_PROPERTY);
       enhanceRelation(BookCategory.BOOKSTORE_PROPERTY, bookstore);
       return this;
    }

    public BookCategoryRequest<T> unselectBookstore(){
       unselectProperty(BookCategory.BOOKSTORE_PROPERTY);
       return this;
    }
    public BookCategoryRequest<T> selectVersion(){
       selectProperty(BookCategory.VERSION_PROPERTY);
       return this;
    }

    /**
     * fill the version with customized rawSqlSegment, TEAQL uses ({rawSqlSegment} AS  version) to fetch version property.
     * @param rawSqlSegment  customized rawSqlSegment
     */




    public BookCategoryRequest<T> unselectVersion(){
       unselectProperty(BookCategory.VERSION_PROPERTY);
       return this;
    }
    public BookCategoryRequest<T> selectBookList(){
       return selectBookListWith(Q.books().selectSelf());
    }

    public BookCategoryRequest<T> selectBookListWith(BookRequest bookList){
       enhanceRelation(BookCategory.BOOK_LIST_PROPERTY, bookList);
       return this;
    }

    public BookCategoryRequest<T> withId(Operator operator, Object... values){
       return appendSearchCriteria(createIdCriteria(operator, values));
    }

    public SearchCriteria createIdCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(BookCategory.ID_PROPERTY, operator, values);
    }

    public BookCategoryRequest<T> withIdIs(Long id){
       return withId(Operator.EQUAL, id);
    }
    public BookCategoryRequest<T> withIdIn(Long... id){
       return withId(Operator.EQUAL, (Object[])id);
    }



    public BookCategoryRequest<T> filterByName(String... name){
      if (name == null || name.length == 0) {
        throw new IllegalArgumentException("filterByName parameter name cannot be empty");
      }
      return appendSearchCriteria(createNameCriteria(Operator.EQUAL, (Object[])name));
    }

    public BookCategoryRequest<T> withName(Operator operator, Object... values){
       return appendSearchCriteria(createNameCriteria(operator, values));
    }

    public BookCategoryRequest<T> withNameIsUnknown(){
       return withName(Operator.IS_NULL);
    }

    public BookCategoryRequest<T> withNameIsKnown(){
       return withName(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createNameCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(BookCategory.NAME_PROPERTY, operator, values);
    }

    public BookCategoryRequest<T> withNameGreaterThan(String name){
       return withName(Operator.GREATER_THAN, name);
    }

    public BookCategoryRequest<T> withNameGreaterThanOrEqualTo(String name){
       return withName(Operator.GREATER_THAN_OR_EQUAL, name);
    }

    public BookCategoryRequest<T> withNameLessThan(String name){
       return withName(Operator.LESS_THAN, name);
    }

    public BookCategoryRequest<T> withNameLessThanOrEqualTo(String name){
       return withName(Operator.LESS_THAN_OR_EQUAL, name);
    }

    public BookCategoryRequest<T> withNameBetween(String startOfName, String endOfName){
       return withName(Operator.BETWEEN, startOfName, endOfName);
    }
    public BookCategoryRequest<T> withNameStartingWith(String name){
       return withName(Operator.BEGIN_WITH, name);
    }
    public BookCategoryRequest<T> withNameContaining(String name){
       return withName(Operator.CONTAIN, name);
    }

    public BookCategoryRequest<T> withNameEndingWith(String name){
       return withName(Operator.END_WITH, name);
    }

    public BookCategoryRequest<T> withNameIs(String name){
       return withName(Operator.EQUAL, name);
    }

    public BookCategoryRequest<T> withNameSoundingLike(String name){
       return withName(Operator.SOUNDS_LIKE, name);
    }



    public BookCategoryRequest<T> filterByCode(String... code){
      if (code == null || code.length == 0) {
        throw new IllegalArgumentException("filterByCode parameter code cannot be empty");
      }
      return appendSearchCriteria(createCodeCriteria(Operator.EQUAL, (Object[])code));
    }

    public BookCategoryRequest<T> withCode(Operator operator, Object... values){
       return appendSearchCriteria(createCodeCriteria(operator, values));
    }

    public BookCategoryRequest<T> withCodeIsUnknown(){
       return withCode(Operator.IS_NULL);
    }

    public BookCategoryRequest<T> withCodeIsKnown(){
       return withCode(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createCodeCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(BookCategory.CODE_PROPERTY, operator, values);
    }

    public BookCategoryRequest<T> withCodeGreaterThan(String code){
       return withCode(Operator.GREATER_THAN, code);
    }

    public BookCategoryRequest<T> withCodeGreaterThanOrEqualTo(String code){
       return withCode(Operator.GREATER_THAN_OR_EQUAL, code);
    }

    public BookCategoryRequest<T> withCodeLessThan(String code){
       return withCode(Operator.LESS_THAN, code);
    }

    public BookCategoryRequest<T> withCodeLessThanOrEqualTo(String code){
       return withCode(Operator.LESS_THAN_OR_EQUAL, code);
    }

    public BookCategoryRequest<T> withCodeBetween(String startOfCode, String endOfCode){
       return withCode(Operator.BETWEEN, startOfCode, endOfCode);
    }
    public BookCategoryRequest<T> withCodeStartingWith(String code){
       return withCode(Operator.BEGIN_WITH, code);
    }
    public BookCategoryRequest<T> withCodeContaining(String code){
       return withCode(Operator.CONTAIN, code);
    }

    public BookCategoryRequest<T> withCodeEndingWith(String code){
       return withCode(Operator.END_WITH, code);
    }

    public BookCategoryRequest<T> withCodeIs(String code){
       return withCode(Operator.EQUAL, code);
    }

    public BookCategoryRequest<T> withCodeSoundingLike(String code){
       return withCode(Operator.SOUNDS_LIKE, code);
    }



    public BookCategoryRequest<T> filterByBookstore(Bookstore... bookstore){
      if (bookstore == null || bookstore.length == 0) {
        throw new IllegalArgumentException("filterByBookstore parameter bookstore cannot be empty");
      }
      return appendSearchCriteria(createBookstoreCriteria(Operator.EQUAL, (Object[])bookstore));
    }

    public BookCategoryRequest<T> withBookstore(Operator operator, Object... values){
       return appendSearchCriteria(createBookstoreCriteria(operator, values));
    }

    public BookCategoryRequest<T> withBookstoreIsUnknown(){
       return withBookstore(Operator.IS_NULL);
    }

    public BookCategoryRequest<T> withBookstoreIsKnown(){
       return withBookstore(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createBookstoreCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(BookCategory.BOOKSTORE_PROPERTY, operator, values);
    }

    public BookCategoryRequest<T> filterByBookstore(Long bookstore){
      if(bookstore == null){
         return this;
      }
      return withBookstore(Operator.EQUAL, bookstore);
    }
    public BookCategoryRequest<T> withBookstoreMatching(BookstoreRequest bookstore){
       return appendSearchCriteria(new SubQuerySearchCriteria(BookCategory.BOOKSTORE_PROPERTY, bookstore, Bookstore.ID_PROPERTY));
    }

    public BookCategoryRequest<T> filterByVersion(Long... version){
      if (version == null || version.length == 0) {
        throw new IllegalArgumentException("filterByVersion parameter version cannot be empty");
      }
      return appendSearchCriteria(createVersionCriteria(Operator.EQUAL, (Object[])version));
    }

    public BookCategoryRequest<T> withVersion(Operator operator, Object... values){
       return appendSearchCriteria(createVersionCriteria(operator, values));
    }

    public BookCategoryRequest<T> withVersionIsUnknown(){
       return withVersion(Operator.IS_NULL);
    }

    public BookCategoryRequest<T> withVersionIsKnown(){
       return withVersion(Operator.IS_NOT_NULL);
    }

    public SearchCriteria createVersionCriteria(Operator operator, Object... values) {
        return createBasicSearchCriteria(BookCategory.VERSION_PROPERTY, operator, values);
    }

    public BookCategoryRequest<T> withVersionGreaterThan(Long version){
       return withVersion(Operator.GREATER_THAN, version);
    }

    public BookCategoryRequest<T> withVersionGreaterThanOrEqualTo(Long version){
       return withVersion(Operator.GREATER_THAN_OR_EQUAL, version);
    }

    public BookCategoryRequest<T> withVersionLessThan(Long version){
       return withVersion(Operator.LESS_THAN, version);
    }

    public BookCategoryRequest<T> withVersionLessThanOrEqualTo(Long version){
       return withVersion(Operator.LESS_THAN_OR_EQUAL, version);
    }

    public BookCategoryRequest<T> withVersionBetween(Long startOfVersion, Long endOfVersion){
       return withVersion(Operator.BETWEEN, startOfVersion, endOfVersion);
    }

    public BookCategoryRequest<T> withBookListMatching(BookRequest bookRequest){
        return appendSearchCriteria(new SubQuerySearchCriteria(BookCategory.ID_PROPERTY, bookRequest, Book.CATEGORY_PROPERTY));
    }

    public BookCategoryRequest<T> withoutBookListMatching(BookRequest bookRequest){
        return appendSearchCriteria(SearchCriteria.not(new SubQuerySearchCriteria(BookCategory.ID_PROPERTY, bookRequest, Book.CATEGORY_PROPERTY)));
    }

    public BookCategoryRequest<T> haveBooks(){
        return withBookListMatching(Q.books().unlimited());
    }

    public BookCategoryRequest<T> haveNoBooks(){
        return withoutBookListMatching(Q.books().unlimited());
    }

    public BookCategoryRequest<T> count(){
        super.count();
        return this;
    }
    public BookCategoryRequest<T> countAs(String retName){
        super.count(retName);
        return this;
    }
    public BookCategoryRequest<T> groupByBookstoreWithDetails(){
       return groupByBookstoreWithDetails(Q.bookstores().unlimited());
    }

    public BookCategoryRequest<T> groupByBookstoreWithDetails(BookstoreRequest subRequest){
       aggregate(BookCategory.BOOKSTORE_PROPERTY, subRequest);
       return this;
    }


    public BookCategoryRequest<T> groupByBooksWithDetails(BookRequest subRequest){
       aggregate(BookCategory.BOOK_LIST_PROPERTY, subRequest);
       return this;
    }

    public BookCategoryRequest<T> groupById(){
       groupBy(BookCategory.ID_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByIdAs(String retName){
       groupBy(retName, BookCategory.ID_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByIdWithFunction(String retName, AggrFunction function){
       groupBy(retName, BookCategory.ID_PROPERTY, function);
       return this;
    }

    public BookCategoryRequest<T> groupByName(){
       groupBy(BookCategory.NAME_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByNameAs(String retName){
       groupBy(retName, BookCategory.NAME_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByNameWithFunction(String retName, AggrFunction function){
       groupBy(retName, BookCategory.NAME_PROPERTY, function);
       return this;
    }

    public BookCategoryRequest<T> groupByCode(){
       groupBy(BookCategory.CODE_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByCodeAs(String retName){
       groupBy(retName, BookCategory.CODE_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByCodeWithFunction(String retName, AggrFunction function){
       groupBy(retName, BookCategory.CODE_PROPERTY, function);
       return this;
    }
    public BookCategoryRequest<T> groupByBookstoreWith(BookstoreRequest subRequest){
       groupBy(BookCategory.BOOKSTORE_PROPERTY, subRequest);
       return this;
    }
    public BookCategoryRequest<T> groupByBookstore(){
       groupBy(BookCategory.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByBookstoreAs(String retName){
       groupBy(retName, BookCategory.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByBookstoreWithFunction(String retName, AggrFunction function){
       groupBy(retName, BookCategory.BOOKSTORE_PROPERTY, function);
       return this;
    }

    public BookCategoryRequest<T> groupByVersion(){
       groupBy(BookCategory.VERSION_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByVersionAs(String retName){
       groupBy(retName, BookCategory.VERSION_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> groupByVersionWithFunction(String retName, AggrFunction function){
       groupBy(retName, BookCategory.VERSION_PROPERTY, function);
       return this;
    }



    public BookCategoryRequest<T> orderByIdAscending(){
       addOrderByAscending(BookCategory.ID_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> orderByIdDescending(){
       addOrderByDescending(BookCategory.ID_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> orderByNameAscending(){
       addOrderByAscending(BookCategory.NAME_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> orderByNameDescending(){
       addOrderByDescending(BookCategory.NAME_PROPERTY);
       return this;
    }
    public BookCategoryRequest<T> orderByNameAscendingUsingGBK(){
       addOrderByAscendingUsingGBK(BookCategory.NAME_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> orderByNameDescendingUsingGBK(){
       addOrderByDescendingUsingGBK(BookCategory.NAME_PROPERTY);
       return this;
    }
    public BookCategoryRequest<T> orderByCodeAscending(){
       addOrderByAscending(BookCategory.CODE_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> orderByCodeDescending(){
       addOrderByDescending(BookCategory.CODE_PROPERTY);
       return this;
    }
    public BookCategoryRequest<T> orderByCodeAscendingUsingGBK(){
       addOrderByAscendingUsingGBK(BookCategory.CODE_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> orderByCodeDescendingUsingGBK(){
       addOrderByDescendingUsingGBK(BookCategory.CODE_PROPERTY);
       return this;
    }
    public BookCategoryRequest<T> orderByBookstoreAscending(){
       addOrderByAscending(BookCategory.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> orderByBookstoreDescending(){
       addOrderByDescending(BookCategory.BOOKSTORE_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> orderByVersionAscending(){
       addOrderByAscending(BookCategory.VERSION_PROPERTY);
       return this;
    }

    public BookCategoryRequest<T> orderByVersionDescending(){
       addOrderByDescending(BookCategory.VERSION_PROPERTY);
       return this;
    }


    public BookCategoryRequest<T> statsFromBooksAs(String name, BookRequest subRequest){
       return statsFromBooksAs(name, subRequest, false);
    }

    public BookCategoryRequest<T> statsFromBooksAs(String name, BookRequest subRequest, boolean singleResult){
       subRequest.setPartitionProperty(Book.CATEGORY_PROPERTY);
       addAggregateDynamicProperty(name, subRequest, singleResult);
       return this;
    }

    public BookCategoryRequest<T> statsFromBooks(BookRequest subRequest){
       return statsFromBooksAs(REFINEMENTS, subRequest);
    }
    public BookstoreRequest rollUpToBookstore(){
       BookstoreRequest bookstore = Q.bookstores().unlimited();
       this.withBookstoreMatching(bookstore)
           .groupByBookstoreWith(bookstore);
       return bookstore;
    }


    public BookCategoryRequest<T> countBooks(){
        return countBooksAs("Count");
    }

    public BookCategoryRequest<T> countBooksAs(String name){
        return countBooksWith(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> countBooksWith(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.count(), true);
    }
    public BookCategoryRequest<T> minPriceOfBooks(){
        return minPriceOfBooksAs("minPriceOfBooks");
    }

    public BookCategoryRequest<T> minPriceOfBooksAs(String name){
        return minPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> minPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.minPrice(), true);
    }
    public BookCategoryRequest<T> maxPriceOfBooks(){
        return maxPriceOfBooksAs("maxPriceOfBooks");
    }

    public BookCategoryRequest<T> maxPriceOfBooksAs(String name){
        return maxPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> maxPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.maxPrice(), true);
    }
    public BookCategoryRequest<T> sumPriceOfBooks(){
        return sumPriceOfBooksAs("sumPriceOfBooks");
    }

    public BookCategoryRequest<T> sumPriceOfBooksAs(String name){
        return sumPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> sumPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.sumPrice(), true);
    }
    public BookCategoryRequest<T> avgPriceOfBooks(){
        return avgPriceOfBooksAs("avgPriceOfBooks");
    }

    public BookCategoryRequest<T> avgPriceOfBooksAs(String name){
        return avgPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> avgPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.avgPrice(), true);
    }
    public BookCategoryRequest<T> standardDeviationPriceOfBooks(){
        return standardDeviationPriceOfBooksAs("stdDevPriceOfBooks");
    }

    public BookCategoryRequest<T> standardDeviationPriceOfBooksAs(String name){
        return standardDeviationPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> standardDeviationPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.standardDeviationPrice(), true);
    }
    public BookCategoryRequest<T> squareRootOfPopulationStandardDeviationPriceOfBooks(){
        return squareRootOfPopulationStandardDeviationPriceOfBooksAs("stdDevPopPriceOfBooks");
    }

    public BookCategoryRequest<T> squareRootOfPopulationStandardDeviationPriceOfBooksAs(String name){
        return squareRootOfPopulationStandardDeviationPriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> squareRootOfPopulationStandardDeviationPriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.squareRootOfPopulationStandardDeviationPrice(), true);
    }
    public BookCategoryRequest<T> sampleVariancePriceOfBooks(){
        return sampleVariancePriceOfBooksAs("varSampPriceOfBooks");
    }

    public BookCategoryRequest<T> sampleVariancePriceOfBooksAs(String name){
        return sampleVariancePriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> sampleVariancePriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.sampleVariancePrice(), true);
    }
    public BookCategoryRequest<T> samplePopulationVariancePriceOfBooks(){
        return samplePopulationVariancePriceOfBooksAs("varPopPriceOfBooks");
    }

    public BookCategoryRequest<T> samplePopulationVariancePriceOfBooksAs(String name){
        return samplePopulationVariancePriceOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> samplePopulationVariancePriceOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.samplePopulationVariancePrice(), true);
    }
    public BookCategoryRequest<T> minStockCountOfBooks(){
        return minStockCountOfBooksAs("minStockCountOfBooks");
    }

    public BookCategoryRequest<T> minStockCountOfBooksAs(String name){
        return minStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> minStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.minStockCount(), true);
    }
    public BookCategoryRequest<T> maxStockCountOfBooks(){
        return maxStockCountOfBooksAs("maxStockCountOfBooks");
    }

    public BookCategoryRequest<T> maxStockCountOfBooksAs(String name){
        return maxStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> maxStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.maxStockCount(), true);
    }
    public BookCategoryRequest<T> sumStockCountOfBooks(){
        return sumStockCountOfBooksAs("sumStockCountOfBooks");
    }

    public BookCategoryRequest<T> sumStockCountOfBooksAs(String name){
        return sumStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> sumStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.sumStockCount(), true);
    }
    public BookCategoryRequest<T> avgStockCountOfBooks(){
        return avgStockCountOfBooksAs("avgStockCountOfBooks");
    }

    public BookCategoryRequest<T> avgStockCountOfBooksAs(String name){
        return avgStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> avgStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.avgStockCount(), true);
    }
    public BookCategoryRequest<T> standardDeviationStockCountOfBooks(){
        return standardDeviationStockCountOfBooksAs("stdDevStockCountOfBooks");
    }

    public BookCategoryRequest<T> standardDeviationStockCountOfBooksAs(String name){
        return standardDeviationStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> standardDeviationStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.standardDeviationStockCount(), true);
    }
    public BookCategoryRequest<T> squareRootOfPopulationStandardDeviationStockCountOfBooks(){
        return squareRootOfPopulationStandardDeviationStockCountOfBooksAs("stdDevPopStockCountOfBooks");
    }

    public BookCategoryRequest<T> squareRootOfPopulationStandardDeviationStockCountOfBooksAs(String name){
        return squareRootOfPopulationStandardDeviationStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> squareRootOfPopulationStandardDeviationStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.squareRootOfPopulationStandardDeviationStockCount(), true);
    }
    public BookCategoryRequest<T> sampleVarianceStockCountOfBooks(){
        return sampleVarianceStockCountOfBooksAs("varSampStockCountOfBooks");
    }

    public BookCategoryRequest<T> sampleVarianceStockCountOfBooksAs(String name){
        return sampleVarianceStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> sampleVarianceStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.sampleVarianceStockCount(), true);
    }
    public BookCategoryRequest<T> samplePopulationVarianceStockCountOfBooks(){
        return samplePopulationVarianceStockCountOfBooksAs("varPopStockCountOfBooks");
    }

    public BookCategoryRequest<T> samplePopulationVarianceStockCountOfBooksAs(String name){
        return samplePopulationVarianceStockCountOfBooksAs(name, Q.books().unlimited());
    }

    public BookCategoryRequest<T> samplePopulationVarianceStockCountOfBooksAs(String name, BookRequest subRequest){
        return statsFromBooksAs(name, subRequest.samplePopulationVarianceStockCount(), true);
    }

   public BookCategoryRequest<T> facetByBookstoreAs(String facetName, BookstoreRequest bookstore){
       return facetByBookstoreAs(facetName, bookstore, true);
   }

   public BookCategoryRequest<T> facetByBookstoreAs(String facetName, BookstoreRequest bookstore, boolean includeAllFacets){
       addFacet(facetName, BookCategory.BOOKSTORE_PROPERTY, bookstore, includeAllFacets);
       return this;
   }


    /**
     * get topN records
     * @param topN  records number
     */
    public BookCategoryRequest<T> top(int topN) {
        super.top(topN);
        return this;
    }

    /**
     * get records from offset(inclusive) to offset+size(exclusive)
     * @param offset record offset
     * @param size records number
     */
    public BookCategoryRequest<T> offset(int offset, int size) {
        super.offset(offset, size);
        return this;
    }

    /**
     * retrieve all records
     */
    public BookCategoryRequest<T> unlimited() {
        super.unlimited();
        return this;
    }

    /**
     * get records of one page
     * @param pageNumber page number(1-based)
     * @param pageSize page size
     */
    public BookCategoryRequest<T> page(int pageNumber, int pageSize) {
        int offset = (pageNumber - 1) * pageSize;
        return offset(offset, pageSize);
   }

    /**
     * get records of one page, default page size is 10
     * @param pageNumber page number(1-based)
     */
    public BookCategoryRequest<T> page(int pageNumber) {
        return page(pageNumber, 10);
   }
}